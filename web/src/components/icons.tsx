import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement>;

function Base({ children, ...props }: P) {
  return (
    <svg viewBox="0 0 24 24" width={18} height={18} fill="none" stroke="currentColor" strokeWidth={1.8}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {children}
    </svg>
  );
}

export const IconDashboard = (p: P) => (
  <Base {...p}><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" />
    <rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></Base>
);
export const IconBuilding = (p: P) => (
  <Base {...p}><path d="M4 21V5a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v16" /><path d="M15 9h3a2 2 0 0 1 2 2v10" />
    <path d="M3 21h18M8 7h3M8 11h3M8 15h3" /></Base>
);
export const IconLayers = (p: P) => (
  <Base {...p}><path d="m12 3 9 5-9 5-9-5 9-5Z" /><path d="m3 13 9 5 9-5" /></Base>
);
export const IconMonitor = (p: P) => (
  <Base {...p}><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></Base>
);
export const IconPulse = (p: P) => (
  <Base {...p}><path d="M3 12h4l2-6 4 12 2-6h6" /></Base>
);
export const IconHistory = (p: P) => (
  <Base {...p}><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v4h4" /><path d="M12 8v4l3 2" /></Base>
);
export const IconChat = (p: P) => (
  <Base {...p}><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z" /></Base>
);
export const IconReport = (p: P) => (
  <Base {...p}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" /><path d="M14 3v5h5" />
    <path d="M9 17v-3M12 17v-6M15 17v-2" /></Base>
);
export const IconSettings = (p: P) => (
  <Base {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" /></Base>
);
export const IconShield = (p: P) => (
  <Base {...p}><path d="M12 3 4 6v6c0 5 3.4 8.3 8 9 4.6-.7 8-4 8-9V6l-8-3Z" /><path d="m9 12 2 2 4-4" /></Base>
);
export const IconLock = (p: P) => (
  <Base {...p}><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 1 1 8 0v3" /></Base>
);
export const IconLogout = (p: P) => (
  <Base {...p}><path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3" /><path d="m10 17-5-5 5-5M5 12h11" /></Base>
);
export const IconMenu = (p: P) => (
  <Base {...p}><path d="M4 6h16M4 12h16M4 18h16" /></Base>
);
export const IconRefresh = (p: P) => (
  <Base {...p}><path d="M21 12a9 9 0 1 1-2.6-6.4" /><path d="M21 4v5h-5" /></Base>
);
export const IconDownload = (p: P) => (
  <Base {...p}><path d="M12 4v11M7 10l5 5 5-5M5 20h14" /></Base>
);
export const IconSearch = (p: P) => (
  <Base {...p}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></Base>
);
export const IconChevron = (p: P) => (
  <Base {...p}><path d="m9 6 6 6-6 6" /></Base>
);
export const IconCheck = (p: P) => (
  <Base {...p}><path d="m5 12 5 5 9-10" /></Base>
);
export const IconX = (p: P) => (
  <Base {...p}><path d="M6 6l12 12M18 6 6 18" /></Base>
);
export const IconAlert = (p: P) => (
  <Base {...p}><path d="M12 3 2 20h20L12 3Z" /><path d="M12 10v4M12 17h.01" /></Base>
);
export const IconDot = (p: P) => (
  <Base {...p}><circle cx="12" cy="12" r="4" fill="currentColor" stroke="none" /></Base>
);
export const IconMinus = (p: P) => (
  <Base {...p}><path d="M6 12h12" /></Base>
);
export const IconClock = (p: P) => (
  <Base {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></Base>
);
export const IconSend = (p: P) => (
  <Base {...p}><path d="M4 12 20 4l-6 16-3-7-7-1Z" /></Base>
);
export const IconPrint = (p: P) => (
  <Base {...p}><path d="M7 9V3h10v6" /><rect x="3" y="9" width="18" height="8" rx="2" /><path d="M7 14h10v7H7z" /></Base>
);
export const IconTrend = (p: P) => (
  <Base {...p}><path d="M3 17l6-6 4 4 8-8" /><path d="M14 7h7v7" /></Base>
);
