export default function WorkspaceSectionLoading() {
  return (
    <main className="workspace-route-screen" aria-live="polite" aria-label="Loading workspace">
      <aside className="route-screen-sidebar" aria-hidden="true">
        <span className="route-screen-logo" />
        {Array.from({ length: 7 }, (_, index) => <span key={index} className="route-screen-nav" />)}
      </aside>
      <section className="route-screen-content">
        <div className="route-screen-title" />
        <div className="route-screen-loader"><span className="route-loader-mark"><i /><i /><i /></span><strong>Loading your business view</strong><small lang="bn">আপনার ব্যবসার তথ্য লোড হচ্ছে…</small></div>
        <div className="route-screen-grid">{Array.from({ length: 5 }, (_, index) => <span key={index} />)}</div>
      </section>
    </main>
  );
}
