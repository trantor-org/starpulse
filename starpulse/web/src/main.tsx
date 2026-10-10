import "./style.css";
import { boot } from "./boot";
import { loadFonts } from "./render/fonts";

void loadFonts();
// the Board draws from this chunk; the React page (navigator, rail, the other views) is a chunk that mounts after that frame
boot(() => void import("./mount"));
