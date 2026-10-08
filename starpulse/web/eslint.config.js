import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

// A feature imports `api/`, `render/`, `shared/` and its own folder, never another feature's, nor `demo/` (the demo answers /api requests through
// `api/apiFetch`) or the App. A feature's tests may reach `demo/` for its route table and fixtures. `render/` composes the features' pure modules
// into the canvas, so only features are bounded.
const FEATURES = ["admin", "dags", "fanout", "forwarding", "kanban", "level", "orbit"];
const boundary = (feature, extra = []) => ({
  files: [`src/features/${feature}/**`],
  ...(extra.length ? { ignores: ["**/*.test.*"] } : {}),
  rules: {
    "no-restricted-imports": ["error", {
      patterns: [
        ...FEATURES.filter((other) => other !== feature).map((other) => ({
          group: [`../${other}`, `../${other}/**`, `**/features/${other}/**`],
          message: `A feature does not import another feature's code: ${feature} may import api/, render/, shared/ and itself.`,
        })),
        ...extra,
      ],
    }],
  },
});
const noDemo = { group: ["**/demo/**", "**/App", "**/main"], message: "A feature reaches the wire through api/apiFetch, never the demo or the App." };

export default tseslint.config(
  { ignores: ["node_modules"] },
  js.configs.recommended,
  tseslint.configs.recommended,
  reactHooks.configs.flat.recommended,
  { languageOptions: { globals: globals.browser } },
  ...FEATURES.flatMap((feature) => [boundary(feature), boundary(feature, [noDemo])]),
);
