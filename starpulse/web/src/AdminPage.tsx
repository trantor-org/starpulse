// The Admin view with the Scheduler, Tracker and Theme cards it hosts: one module, so the page loads them as one chunk when Admin first opens.
import { useState } from "react";
import { Admin } from "./features/admin/Admin";
import { TrackerCard } from "./features/kanban/ConnectTracker";
import type { AdminStore } from "./features/admin/adminPrefs";
import type { HistoryWindowStore } from "./features/admin/historyWindow";
import { ThemeCard } from "./features/admin/theme/ThemeCard";
import type { ThemeStore } from "./features/admin/theme/themeStore";
import { QuietHoursStore } from "./features/admin/quietHours";
import { SchedulerCard } from "./features/scheduler/SchedulerCard";
import { SchedulerStore } from "./features/scheduler/scheduler";

export function AdminPage({ store, theme, window, hint }: { store: AdminStore; theme: ThemeStore; window: HistoryWindowStore; hint?: string | null }) {
  const [quiet] = useState(() => new QuietHoursStore());
  const [scheduler] = useState(() => new SchedulerStore());
  return (
    <Admin store={store} window={window} tracker={<TrackerCard hint={hint} />} theme={<ThemeCard theme={theme} />}
      scheduler={(clock) => <SchedulerCard store={scheduler} quiet={quiet} clock={clock} />} />
  );
}
