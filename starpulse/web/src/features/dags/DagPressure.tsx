// The DAGs view's run pressure, drawn in the navigator below the Queues: the DAGs that spent the most run-hours in a week and the Runner CPU as one share of all the cores.
import { Card } from "../../shared/Card";
import { cpuPercent, runHours, short, type DagData } from "./dagsModel";

/** Run-hours as a figure: one decimal below ten, whole above. */
const hours = (h: number) => `${h < 10 ? Math.round(h * 10) / 10 : Math.round(h)}h`;

/** One labelled bar: `fill` is the share of its track from 0 to 100, `tone` the colour the figure and the bar take. */
const Bar = ({ label, text, fill, tone, title }: { label: string; text: string; fill: number; tone?: "busy" | "full"; title?: string }) => (
  <div className={`q${tone ? ` ${tone}` : ""}`} title={title ?? label}>
    <div className="r"><span>{label}</span><b>{text}</b></div>
    <div className="m"><i style={{ width: `${fill}%` }} /></div>
  </div>
);

export function DagPressure({ data }: { data: DagData | null }) {
  const spent = data ? runHours(data.facts) : [];
  const cpu = data ? cpuPercent(data.cpu) : null;
  return (
    <>
      <Card title="Run-hours" id="runhours">
        {spent.length ? spent.map((d) => <Bar key={d.name} label={short(d.name)} text={hours(d.hours)} fill={(100 * d.hours) / spent[0].hours} title={d.name} />) : <div className="none">no runs read</div>}
      </Card>
      <Card title="Runner CPU" id="cpu">
        <Bar label={cpu === null ? "not read" : "of all cores"} text={cpu === null ? "" : `${Math.round(cpu)}%`} fill={cpu ?? 0} tone={cpu === null ? undefined : cpu >= 90 ? "full" : cpu > 0 ? "busy" : undefined} />
      </Card>
    </>
  );
}
