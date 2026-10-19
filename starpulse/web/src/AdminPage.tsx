// The Admin view with the Autopilot and Tracker cards it hosts: one module, so the page loads them as one chunk when Admin first opens.
import { useState } from "react";
import { Admin } from "./features/admin/Admin";
import { TrackerCard } from "./features/kanban/ConnectTracker";
import type { AdminStore } from "./features/admin/adminPrefs";
import type { HistoryWindowStore } from "./features/admin/historyWindow";
import { QuietHoursStore } from "./features/admin/quietHours";
import { AutopilotCard } from "./features/autopilot/AutopilotCard";
import { AutopilotStore } from "./features/autopilot/autopilot";

export function AdminPage({ store, window, hint }: { store: AdminStore; window: HistoryWindowStore; hint?: string | null }) {
  const [quiet] = useState(() => new QuietHoursStore());
  const [autopilot] = useState(() => new AutopilotStore());
  return (
    <Admin store={store} window={window} tracker={<TrackerCard hint={hint} />}
      autopilot={(clock) => <AutopilotCard store={autopilot} quiet={quiet} clock={clock} />} />
  );
}
