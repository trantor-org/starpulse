"""Opening the inbox on a database that cannot be migrated leaves no engine behind."""

from unittest.mock import patch

import pytest

from starpulse.github.adapters.outbound import inbox
from starpulse.github.adapters.outbound.inbox import SqlInbox


def test_a_failed_migration_disposes_the_engine_it_opened(tmp_path) -> None:
    with patch.object(inbox, "create_engine") as create, patch.object(inbox, "migrate_chain", side_effect=OSError("locked")):
        with pytest.raises(OSError, match="locked"):
            SqlInbox(f"sqlite:///{tmp_path / 'g.sqlite'}")
    create.return_value.dispose.assert_called_once_with()
