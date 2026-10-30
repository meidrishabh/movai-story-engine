import { Badge, Button } from '../../shared/ui'
import { formatDuration } from '../../shared/lib/format'
import type { BeatAction, BeatItem } from './types'

export type BeatVariant = 'removed' | 'disputed' | 'restored'

const DISPUTE_REASON: Record<NonNullable<BeatItem['why']>, string> = {
  reused_later: 'Kept because something in it comes back later.',
  judge_keep: 'Kept because the second reviewer disagreed with the cut.',
  judge_missing: 'Kept because the second reviewer gave no answer.',
}

const ACTION: Record<BeatVariant, { action: BeatAction; label: string } | null> = {
  removed: { action: 'keep', label: 'Keep this beat' },
  restored: { action: 'cut', label: 'Cut this beat' },
  disputed: { action: 'cut', label: 'Cut this beat' },
}

interface Props {
  item: BeatItem
  variant: BeatVariant
  busy: boolean
  onDecide: (action: BeatAction) => void
}

/** One beat in the filler review. Removed beats are greyed out and struck through but stay readable. */
export function BeatRow({ item, variant, busy, onDecide }: Props) {
  const action = ACTION[variant]
  return (
    <div className={`beat beat-${variant}`}>
      <div className="row row-between">
        <div className="row">
          <Badge tone={variant === 'removed' ? 'neutral' : variant === 'disputed' ? 'warn' : 'ok'}>
            {variant === 'removed' ? 'Removed' : variant === 'disputed' ? 'Reviewers disagree' : 'Kept by you'}
          </Badge>
          <span className="muted">
            Unit {item.unit} · {item.unit_title}
          </span>
          {item.by === 'user' && variant === 'removed' && <Badge>Cut by you</Badge>}
        </div>
        <span className="muted mono">{formatDuration(item.seconds)}</span>
      </div>

      <p className="beat-text">{item.beat_text ?? `The whole unit: ${item.unit_title}`}</p>

      <div className="beat-reasons">
        {item.reason && <span>Proposed: {item.reason}</span>}
        {item.judge_reason && <span>Second reviewer: {item.judge_reason}</span>}
        {variant === 'disputed' && item.why && <span>{DISPUTE_REASON[item.why]}</span>}
        {item.reused_later.length > 0 && <span>Comes back later: {item.reused_later.join(', ')}</span>}
      </div>

      {action && (
        <div className="row">
          <Button variant="secondary" busy={busy} onClick={() => onDecide(action.action)}>
            {action.label}
          </Button>
        </div>
      )}
    </div>
  )
}
