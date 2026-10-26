// What `mermaid` resolves to in the one-file demo build: its draw rejects, so a diagram stays the mermaid source in a code fence.
export default {
  initialize() {},
  render: () => Promise.reject(new Error("mermaid is not in the one-file demo")),
};
