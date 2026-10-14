const number = new Intl.NumberFormat();

/** A titled group of numbers at a glance. */
export function Figures({
  title,
  figures,
}: {
  title: string;
  figures: [label: string, value: number][];
}) {
  const id = `figures-${title.toLowerCase().replace(/\s+/g, "-")}`;
  return (
    <section className="card" aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      <dl className="figures">
        {figures.map(([label, value]) => (
          <div key={label} className="figure">
            <dt>{label}</dt>
            <dd>{number.format(value)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
