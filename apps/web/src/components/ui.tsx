import type { ReactNode, SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const base = (props: IconProps) => ({
  width: 16,
  height: 16,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
  ...props,
});

export const PlayIcon = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="M7 4.5v15l12-7.5z" fill="currentColor" stroke="none" />
  </svg>
);
export const PauseIcon = (props: IconProps) => (
  <svg {...base(props)}>
    <rect x="6" y="4.5" width="4" height="15" rx="1" fill="currentColor" stroke="none" />
    <rect x="14" y="4.5" width="4" height="15" rx="1" fill="currentColor" stroke="none" />
  </svg>
);
export const RestartIcon = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="M3 12a9 9 0 1 0 3-6.7" />
    <path d="M3 4v5h5" />
  </svg>
);
export const CheckIcon = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="m5 12.5 4.5 4.5L19 7.5" />
  </svg>
);
export const SparkIcon = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6" />
  </svg>
);
export const ExternalIcon = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
  </svg>
);
export const ChevronIcon = (props: IconProps) => (
  <svg {...base(props)}>
    <path d="m6 9 6 6 6-6" />
  </svg>
);

export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
  testId,
}: {
  label: string;
  value: T;
  options: ReadonlyArray<{ value: T; label: ReactNode; title?: string }>;
  onChange: (value: T) => void;
  testId?: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      data-testid={testId}
      className="flex flex-wrap gap-1 rounded-xl bg-ink-950/60 p-1 ring-1 ring-white/5"
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            title={option.title}
            onClick={() => onChange(option.value)}
            className={`flex min-w-0 flex-1 items-center justify-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium transition ${
              active ? "bg-white text-ink-950 shadow" : "text-slate-300 hover:bg-white/5 hover:text-white"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

type Tone = "slate" | "mint" | "gold" | "live" | "violet" | "sky";

const TONES: Record<Tone, string> = {
  slate: "bg-white/8 text-slate-300 ring-1 ring-white/10",
  mint: "bg-mint/12 text-mint ring-1 ring-mint/25",
  gold: "bg-gold/14 text-gold ring-1 ring-gold/30",
  live: "bg-live/15 text-live ring-1 ring-live/30",
  violet: "bg-violet/15 text-violet ring-1 ring-violet/30",
  sky: "bg-sky/15 text-sky ring-1 ring-sky/30",
};

export function Badge({
  children,
  tone = "slate",
  title,
  testId,
}: {
  children: ReactNode;
  tone?: Tone;
  title?: string;
  testId?: string;
}) {
  return (
    <span
      title={title}
      data-testid={testId}
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[0.7rem] font-semibold ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="eyebrow text-slate-400">{children}</h2>
      {aside}
    </div>
  );
}
