// The Admin view with the Tracker and Forwarding cards it hosts: one module, so the page loads them as one chunk when Admin first opens.
import { Admin } from "./features/admin/Admin";
import { TrackerCard } from "./features/kanban/ConnectTracker";
import type { AdminStore } from "./features/admin/adminPrefs";
import type { HistoryWindowStore } from "./features/admin/historyWindow";
import { ForwardingCard } from "./features/forwarding/ForwardingCard";
import type { ForwardingStore } from "./features/forwarding/forwarding";

export function AdminPage({ store, window, forwarding, hint }: { store: AdminStore; window: HistoryWindowStore; forwarding: ForwardingStore; hint?: string | null }) {
  return <Admin store={store} window={window} tracker={<TrackerCard hint={hint} />} forwarding={(clock) => <ForwardingCard store={forwarding} clock={clock} />} />;
}
