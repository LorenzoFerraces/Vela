type PlaceholderPageProps = {
  title: string
}

export default function PlaceholderPage({ title }: PlaceholderPageProps) {
  return (
    <section className="placeholder">
      <h1 className="placeholder__title">{title}</h1>
      <p className="placeholder__text">This section is coming soon.</p>
    </section>
  )
}
