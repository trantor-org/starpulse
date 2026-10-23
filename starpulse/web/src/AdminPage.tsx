// The Admin view with the Scheduler and Tracker cards it hosts: one module, so the page loads them as one chunk when Admin first opens.
import { useState } from "react";
import { Admin } from "./features/admin/Admin";
import { TrackerCard } from "./features/kanban/ConnectTracker";
import type { AdminStore } from "./features/admin/adminPrefs";
import type { HistoryWindowStore } from "./features/admin/historyWindow";
import { QuietHoursStore } from "./features/admin/quietHours";
import { SchedulerCard } from "./features/scheduler/SchedulerCard";
import { SchedulerStore } from "./features/scheduler/scheduler";

export function AdminPage({ store, window, hint }: { store: AdminStore; window: HistoryWindowStore; hint?: string | null }) {
  const [quiet] = useState(() => new QuietHoursStore());
  const [scheduler] = useState(() => new SchedulerStore());
  return (
    <Admin store={store} window={window} tracker={<TrackerCard hint={hint} />}
      scheduler={(clock) => <SchedulerCard store={scheduler} quiet={quiet} clock={clock} />} />
  );
}
