import { useState } from "react";
import { postResume } from "./resume";

/** The Resume button of a parked task, with an optional reply that becomes the recreated session's first message, and the link to that session. */
export function ResumeControl({ task, recorded, disabled }: { task: string; recorded: string | null; disabled: boolean }) {
  const [text, setText] = useState("");
  const [phase, setPhase] = useState<"idle" | "sending">("idle");
  const [url, setUrl] = useState<string | null>(null);
  const [failure, setFailure] = useState("");
  const resume = async () => {
    setPhase("sending");
    setFailure("");
    const reply = await postResume(task, text);
    setPhase("idle");
    if (reply.ok) {
      setUrl(reply.url);
      setText("");
    } else setFailure(reply.reason);
  };
  const link = url ?? recorded;
  return (
    <div className="resume">
      <input type="text" value={text} placeholder="Reply for the resumed session (optional)" aria-label="Reply for the resumed session"
        onChange={(e) => setText(e.currentTarget.value)} />
      <button className="startbtn" disabled={disabled || phase === "sending"} onClick={() => void resume()}>
        {phase === "sending" ? "Resuming…" : "↻ Resume"}
      </button>
      {failure && <span className="bad" role="alert">{failure}</span>}
      {link && <a href={link} target="_blank" rel="noreferrer">Open resumed session ↗</a>}
    </div>
  );
}
