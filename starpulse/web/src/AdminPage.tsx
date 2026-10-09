// The Admin view with the forwarding card it hosts: one module, so the page loads both as one chunk when Admin first opens.
import { Admin } from "./features/admin/Admin";
import type { AdminStore } from "./features/admin/adminPrefs";
import type { HistoryWindowStore } from "./features/admin/historyWindow";
import { ForwardingCard } from "./features/forwarding/ForwardingCard";
import type { ForwardingStore } from "./features/forwarding/forwarding";

export function AdminPage({ store, window, forwarding }: { store: AdminStore; window: HistoryWindowStore; forwarding: ForwardingStore }) {
  return <Admin store={store} window={window} forwarding={(clock) => <ForwardingCard store={forwarding} clock={clock} />} />;
}
