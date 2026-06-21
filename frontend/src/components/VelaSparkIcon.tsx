import { StarFourIcon } from '@phosphor-icons/react/StarFour'

type VelaSparkIconProps = {
  size?: number
  className?: string
}

export function VelaSparkIcon({ size = 22, className }: VelaSparkIconProps) {
  return (
    <StarFourIcon
      size={size}
      weight="fill"
      className={className}
      aria-hidden
      color="currentColor"
    />
  )
}
