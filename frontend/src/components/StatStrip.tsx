interface StatItem {
  label: string;
  value: string;
  tone?: 'default' | 'positive' | 'muted';
}

interface StatStripProps {
  items: StatItem[];
}

export function StatStrip({ items }: StatStripProps) {
  return (
    <section className="stat-strip">
      {items.map((item) => (
        <article key={item.label} className="stat-block">
          <span className="stat-label">{item.label}</span>
          <strong className={`stat-value ${item.tone ?? 'default'}`}>{item.value}</strong>
        </article>
      ))}
    </section>
  );
}
