from __future__ import annotations

import tempfile
import unittest

from goreecloud_home.journal import EventJournal
from goreecloud_home.storage import LATEST_SCHEMA_VERSION


class EventJournalTests(unittest.TestCase):
    def test_events_survive_reopen_and_sequence_is_monotonic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/events.db"
            journal = EventJournal(path)
            first = journal.append("home.created", "home", {"name": "Home"})
            second = journal.append("room.created", "room", {"home_id": "home"})
            journal.close()

            reopened = EventJournal(path)
            events = reopened.list_since()
            self.assertEqual(LATEST_SCHEMA_VERSION, reopened.database.schema_version)
            reopened.close()

            self.assertEqual([first.sequence, second.sequence], [event.sequence for event in events])
            self.assertLess(first.sequence, second.sequence)
            self.assertEqual("home.created", events[0].event_type)
            self.assertEqual({"name": "Home"}, events[0].payload)

    def test_list_since_is_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = EventJournal(f"{directory}/events.db")
            first = journal.append("one", "a", {})
            journal.append("two", "b", {})
            events = journal.list_since(first.sequence)
            journal.close()
            self.assertEqual(["two"], [event.event_type for event in events])


if __name__ == "__main__":
    unittest.main()
