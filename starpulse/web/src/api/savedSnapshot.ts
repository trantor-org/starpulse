// The last Board the page drew, kept in IndexedDB so a reload while the server is down or restarting still has cards to draw.
// localStorage would hold it too small and block the main thread on every write; IndexedDB stores the object as it is.
import type { Snapshot } from ".";

/** Where the page keeps a snapshot between loads. */
export interface SnapshotCache {
  /** The kept snapshot, or null when none is kept or this page build did not write it. */
  read(): Promise<Snapshot | null>;
  /** Replaces the kept snapshot; rejects when the browser refuses it (a full quota). */
  write(snap: Snapshot): Promise<void>;
}

/** A snapshot is read back only by the page build that wrote it: a newer build may read another shape. */
const BUILD = import.meta.url;
const NAME = "starpulse";
const STORE = "kept";
const KEY = "snapshot";

const connect = () =>
  new Promise<IDBDatabase>((resolve, reject) => {
    const req = indexedDB.open(NAME, 1);
    req.onupgradeneeded = () => void req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });

/** The browser's store, or null where there is none (a private window, a test): the page then works as it did, with nothing kept. */
export function browserCache(): SnapshotCache | null {
  if (typeof indexedDB === "undefined") return null;
  return {
    async read() {
      const db = await connect();
      try {
        const row = await new Promise<{ build: string; snap: Snapshot } | undefined>((resolve, reject) => {
          const req = db.transaction(STORE).objectStore(STORE).get(KEY);
          req.onsuccess = () => resolve(req.result);
          req.onerror = () => reject(req.error);
        });
        return row?.build === BUILD ? row.snap : null;
      } finally {
        db.close();
      }
    },
    async write(snap) {
      const db = await connect();
      try {
        await new Promise<void>((resolve, reject) => {
          const tx = db.transaction(STORE, "readwrite");
          tx.objectStore(STORE).put({ build: BUILD, snap }, KEY);
          tx.oncomplete = () => resolve();
          tx.onerror = tx.onabort = () => reject(tx.error);
        });
      } finally {
        db.close();
      }
    },
  };
}
