type VelaMarkIconProps = {
  size?: number
  className?: string
}

export function VelaMarkIcon({ size = 14, className }: VelaMarkIconProps) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <path fill="currentColor" d="M12 5.5 18.75 19.5H5.25L12 5.5Z" />
    </svg>
  )
}
