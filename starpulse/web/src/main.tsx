import "./style.css";
import { boot } from "./boot";
import { embedded } from "./demo/host";
import { loadFonts } from "./render/fonts";

void loadFonts();

/** An embedded fixture or `?demo` loads the demo tree before the Board starts; a plain served page never does. */
function start(): void {
  // the Board draws from this chunk; the React page (navigator, rail, the other views) is a chunk that mounts after that frame
  boot(() => void import("./mount"));
}

const wantsDemo = embedded() || new URLSearchParams(location.search).has("demo");
if (wantsDemo) {
  void import("./demo/demo").then(({ ensureDemoServer }) => {
    ensureDemoServer();
    start();
  });
} else {
  start();
}
