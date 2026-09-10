/** Wordmark + shield, links back to the landing page. Appears top-left
 *  in every page header. `onClick` lets a page guard the navigation —
 *  the session page confirms before abandoning a running chat. */
export default function Brand({
  onClick,
}: {
  onClick?: React.MouseEventHandler<HTMLAnchorElement>;
}) {
  return (
    <a
      href="/"
      onClick={onClick}
      className="group inline-flex items-center gap-2.5 rounded text-sm font-semibold tracking-tight transition hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
    >
      <span className="grid h-[22px] w-[22px] place-items-center rounded-md bg-accent/10 text-accent transition group-hover:bg-accent/20">
        <svg
          width="13"
          height="13"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden
        >
          <path d="M12 3 4 7v6c0 5 3.5 7.5 8 8 4.5-.5 8-3 8-8V7z" />
        </svg>
      </span>
      Career Assistant
    </a>
  );
}
