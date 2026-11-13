import type * as React from 'react';

type IconProps = React.ComponentProps<'svg'>;

function Icon({ children, ...props }: IconProps) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      aria-hidden="true"
      {...props}
      style={{ display: 'block', flexShrink: 0, ...props.style }}
    >
      {children}
    </svg>
  );
}

export const CaretUpDownIcon = (p: IconProps) => (
  <Icon {...p} stroke="none" fill="currentColor">
    <path d="M11 10H5l3 3.5zm0-4H5l3-3.5z" />
  </Icon>
);
export const CaretRightIcon = (p: IconProps) => (
  <Icon {...p} stroke="none" fill="currentColor">
    <path d="M6 12V4l4.5 4z" />
  </Icon>
);
export const CheckIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="m2.5 8.5 4 4 7-9" />
  </Icon>
);
export const PlusIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M8 2v12M2 8h12" />
  </Icon>
);
export const MinusIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M2 8h12" />
  </Icon>
);
export const ArrowUpIcon = (p: IconProps) => (
  <Icon {...p} strokeWidth={1.5}>
    <path d="M8 13V3M3.5 7.5 8 3l4.5 4.5" />
  </Icon>
);
export const StopIcon = (p: IconProps) => (
  <Icon {...p} stroke="none" fill="currentColor">
    <rect x="4" y="4" width="8" height="8" />
  </Icon>
);
export const RefreshIcon = (p: IconProps) => (
  <Icon {...p} strokeWidth={1.25}>
    <path d="M13 8a5 5 0 1 1-1.5-3.6M13 2.5V5h-2.5" />
  </Icon>
);
export const SunMoonIcon = (p: IconProps) => (
  <Icon {...p} strokeWidth={1.25}>
    <circle cx="8" cy="8" r="5" />
    <path d="M8 3a5 5 0 0 0 0 10z" fill="currentColor" />
  </Icon>
);
export const SlidersIcon = (p: IconProps) => (
  <Icon {...p} strokeWidth={1.25}>
    <path d="M2 4h7m3 0h2M2 12h2m3 0h7M9 2.5v3M5 10.5v3" />
  </Icon>
);
export const TrashIcon = (p: IconProps) => (
  <Icon {...p} strokeWidth={1.25}>
    <path d="M2.5 4h11M6 4V2.5h4V4m-6 0 .7 9.5h6.6L12 4" />
  </Icon>
);
export const GearIcon = (p: IconProps) => (
  <Icon {...p} stroke="none" fill="currentColor">
    <path d="M7 0h2l.4 2.1 1.4.6 1.8-1.2 1.4 1.4-1.2 1.8.6 1.4L16 7v2l-2.1.4-.6 1.4 1.2 1.8-1.4 1.4-1.8-1.2-1.4.6L9 16H7l-.4-2.1-1.4-.6-1.8 1.2-1.4-1.4 1.2-1.8-.6-1.4L0 9V7l2.1-.4.6-1.4-1.2-1.8 1.4-1.4 1.8 1.2 1.4-.6zm1 5a3 3 0 1 0 0 6 3 3 0 0 0 0-6" />
  </Icon>
);
