type Props = {
  title: string;
  eyebrow: string;
  children?: React.ReactNode;
};

export function PlaceholderRoute({title, eyebrow, children}: Props) {
  return (
    <section className="page-section" aria-labelledby={`${title}-title`}>
      <p className="eyebrow">{eyebrow}</p>
      <h1 id={`${title}-title`}>{title}</h1>
      {children ? <div className="empty-state">{children}</div> : null}
    </section>
  );
}
