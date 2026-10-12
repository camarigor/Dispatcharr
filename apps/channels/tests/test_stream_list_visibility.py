"""The stream list, stream retrieve and by-ids give a non-admin user only
streams of channels they can access: a stream URL usually carries the
provider login, so it follows the same rule as channels/<id>/streams/."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.channels.models import (
    Channel,
    ChannelProfile,
    ChannelProfileMembership,
    Stream,
)

User = get_user_model()


def _make_user(username, level):
    user = User.objects.create_user(username=username, password="testpass123")
    user.user_level = level
    user.save()
    return user


class StreamListVisibilityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.allowed = Channel.objects.create(channel_number=1, name="Allowed")
        self.other_profile = Channel.objects.create(
            channel_number=2, name="Other profile"
        )
        self.mine = Stream.objects.create(
            name="Mine", url="http://provider-a.example/live/a_user/a_secret/1.ts"
        )
        self.theirs = Stream.objects.create(
            name="Theirs", url="http://provider-b.example/live/b_user/b_secret/1.ts"
        )
        self.orphan = Stream.objects.create(
            name="Orphan", url="http://provider-b.example/live/b_user/b_secret/2.ts"
        )
        self.allowed.streams.add(self.mine)
        self.other_profile.streams.add(self.theirs)

        # The assigned profile switches "Other profile" off, so its stream is
        # out of reach for the restricted user.
        self.profile = ChannelProfile.objects.create(name="Assigned")
        ChannelProfileMembership.objects.filter(
            channel_profile=self.profile, channel=self.other_profile
        ).update(enabled=False)

        self.standard = _make_user("standard-stream-list", 1)
        self.standard.channel_profiles.add(self.profile)
        self.unrestricted = _make_user("unrestricted-stream-list", 1)
        self.admin = _make_user("admin-stream-list", 10)

    def _names(self, response):
        rows = response.data
        if isinstance(rows, dict):
            rows = rows["results"]
        return {row["name"] for row in rows}

    def _list(self, user):
        self.client.force_authenticate(user=user)
        return self.client.get("/api/channels/streams/")

    def _by_ids(self, user):
        self.client.force_authenticate(user=user)
        return self.client.post(
            "/api/channels/streams/by-ids/",
            {"ids": [self.mine.id, self.theirs.id, self.orphan.id]},
            format="json",
        )

    def test_list_returns_only_streams_of_accessible_channels(self):
        response = self._list(self.standard)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._names(response), {"Mine"})

    def test_retrieve_outside_assigned_profiles_is_not_found(self):
        self.client.force_authenticate(user=self.standard)
        outside = self.client.get(f"/api/channels/streams/{self.theirs.id}/")
        inside = self.client.get(f"/api/channels/streams/{self.mine.id}/")
        self.assertEqual(outside.status_code, 404)
        self.assertEqual(inside.status_code, 200)

    def test_by_ids_drops_streams_outside_assigned_profiles(self):
        response = self._by_ids(self.standard)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._names(response), {"Mine"})

    def test_user_without_profiles_gets_streams_of_every_visible_channel(self):
        self.assertEqual(self._names(self._list(self.unrestricted)), {"Mine", "Theirs"})
        self.assertEqual(
            self._names(self._by_ids(self.unrestricted)), {"Mine", "Theirs"}
        )

    def test_admin_gets_every_stream(self):
        everything = {"Mine", "Theirs", "Orphan"}
        self.assertEqual(self._names(self._list(self.admin)), everything)
        self.assertEqual(self._names(self._by_ids(self.admin)), everything)
