import { useState } from 'react'
import type { ScalingMetric, ScalingPolicyRequest } from '../../api/client'

export type { ScalingPolicyRequest }

type ContainersRunScalingFieldsProps = {
  scalingPolicy: ScalingPolicyRequest | null
  onScalingPolicyChange: (policy: ScalingPolicyRequest | null) => void
}

const DEFAULT_POLICY: ScalingPolicyRequest = {
  enabled: true,
  min_replicas: 1,
  max_replicas: 3,
  metric: 'cpu_percent',
  scale_up_threshold: 70,
  scale_down_threshold: 30,
  cooldown_seconds: 60,
  scale_up_stabilization_seconds: 120,
  scale_down_stabilization_seconds: 120,
}

const METRIC_LABELS: Record<ScalingMetric, string> = {
  cpu_percent: 'CPU %',
  requests_per_second: 'Requests / sec',
}

export function ContainersRunScalingFields({
  scalingPolicy,
  onScalingPolicyChange,
}: ContainersRunScalingFieldsProps) {
  const [expanded, setExpanded] = useState(false)
  const enabled = scalingPolicy !== null

  function handleToggleEnabled() {
    onScalingPolicyChange(enabled ? null : { ...DEFAULT_POLICY })
  }

  function patch(updates: Partial<ScalingPolicyRequest>) {
    if (!scalingPolicy) return
    onScalingPolicyChange({ ...scalingPolicy, ...updates })
  }

  return (
    <div className="containers-form__advanced">
      <button
        type="button"
        className="btn btn--ghost containers-form__advanced-toggle"
        aria-expanded={expanded}
        onClick={() => setExpanded((open) => !open)}
      >
        <span>Auto-scaling</span>
        <span
          className="containers-form__advanced-chevron"
          aria-hidden="true"
        >
          ›
        </span>
      </button>
      {expanded ? (
        <div className="containers-form__advanced-body">
          <div className="containers-scaling-toggle">
            <label className="containers-form__label" htmlFor="scaling-enabled">
              Enable auto-scaling
            </label>
            <input
              id="scaling-enabled"
              type="checkbox"
              checked={enabled}
              onChange={handleToggleEnabled}
            />
          </div>

          {scalingPolicy ? (
            <div className="containers-scaling-fields">
              <div className="containers-scaling-row">
                <div className="containers-scaling-field">
                  <label
                    className="containers-form__label"
                    htmlFor="scaling-min-replicas"
                  >
                    Min replicas
                  </label>
                  <input
                    id="scaling-min-replicas"
                    className="containers-form__input containers-form__input--short"
                    type="number"
                    min={1}
                    max={20}
                    value={scalingPolicy.min_replicas}
                    onChange={(event) =>
                      patch({ min_replicas: parseInt(event.target.value, 10) || 1 })
                    }
                  />
                </div>

                <div className="containers-scaling-field">
                  <label
                    className="containers-form__label"
                    htmlFor="scaling-max-replicas"
                  >
                    Max replicas
                  </label>
                  <input
                    id="scaling-max-replicas"
                    className="containers-form__input containers-form__input--short"
                    type="number"
                    min={1}
                    max={20}
                    value={scalingPolicy.max_replicas}
                    onChange={(event) =>
                      patch({ max_replicas: parseInt(event.target.value, 10) || 1 })
                    }
                  />
                </div>
              </div>

              <label className="containers-form__label" htmlFor="scaling-metric">
                Scale metric
              </label>
              <select
                id="scaling-metric"
                className="containers-form__input"
                value={scalingPolicy.metric}
                onChange={(event) =>
                  patch({ metric: event.target.value as ScalingMetric })
                }
              >
                {(Object.keys(METRIC_LABELS) as ScalingMetric[]).map((metric) => (
                  <option key={metric} value={metric}>
                    {METRIC_LABELS[metric]}
                  </option>
                ))}
              </select>

              <div className="containers-scaling-row">
                <div className="containers-scaling-field">
                  <label
                    className="containers-form__label"
                    htmlFor="scaling-up-threshold"
                  >
                    Scale-up above
                  </label>
                  <div className="containers-scaling-threshold">
                    <input
                      id="scaling-up-threshold"
                      className="containers-form__input containers-form__input--short"
                      type="number"
                      min={0}
                      max={100}
                      step={1}
                      value={scalingPolicy.scale_up_threshold}
                      onChange={(event) =>
                        patch({
                          scale_up_threshold:
                            parseFloat(event.target.value) || 0,
                        })
                      }
                    />
                    <span className="containers-scaling-threshold__unit">
                      {scalingPolicy.metric === 'cpu_percent' ? '%' : 'req/s'}
                    </span>
                  </div>
                </div>

                <div className="containers-scaling-field">
                  <label
                    className="containers-form__label"
                    htmlFor="scaling-down-threshold"
                  >
                    Scale-down below
                  </label>
                  <div className="containers-scaling-threshold">
                    <input
                      id="scaling-down-threshold"
                      className="containers-form__input containers-form__input--short"
                      type="number"
                      min={0}
                      max={100}
                      step={1}
                      value={scalingPolicy.scale_down_threshold}
                      onChange={(event) =>
                        patch({
                          scale_down_threshold:
                            parseFloat(event.target.value) || 0,
                        })
                      }
                    />
                    <span className="containers-scaling-threshold__unit">
                      {scalingPolicy.metric === 'cpu_percent' ? '%' : 'req/s'}
                    </span>
                  </div>
                </div>
              </div>

              <div className="containers-scaling-row">
                <div className="containers-scaling-field">
                  <label
                    className="containers-form__label"
                    htmlFor="scaling-up-stabilization"
                  >
                    Hold before scale-up
                  </label>
                  <div className="containers-scaling-threshold">
                    <input
                      id="scaling-up-stabilization"
                      className="containers-form__input containers-form__input--short"
                      type="number"
                      min={0.5}
                      max={60}
                      step={0.5}
                      value={scalingPolicy.scale_up_stabilization_seconds / 60}
                      onChange={(event) =>
                        patch({
                          scale_up_stabilization_seconds: Math.round(
                            (parseFloat(event.target.value) || 2) * 60
                          ),
                        })
                      }
                    />
                    <span className="containers-scaling-threshold__unit">min</span>
                  </div>
                </div>

                <div className="containers-scaling-field">
                  <label
                    className="containers-form__label"
                    htmlFor="scaling-down-stabilization"
                  >
                    Hold before scale-down
                  </label>
                  <div className="containers-scaling-threshold">
                    <input
                      id="scaling-down-stabilization"
                      className="containers-form__input containers-form__input--short"
                      type="number"
                      min={0.5}
                      max={60}
                      step={0.5}
                      value={scalingPolicy.scale_down_stabilization_seconds / 60}
                      onChange={(event) =>
                        patch({
                          scale_down_stabilization_seconds: Math.round(
                            (parseFloat(event.target.value) || 2) * 60
                          ),
                        })
                      }
                    />
                    <span className="containers-scaling-threshold__unit">min</span>
                  </div>
                </div>
              </div>
              <p className="containers-muted containers-form__hint">
                Metric must stay past the threshold for this long before scaling.
              </p>

              <label
                className="containers-form__label"
                htmlFor="scaling-cooldown"
              >
                Cooldown (seconds)
              </label>
              <input
                id="scaling-cooldown"
                className="containers-form__input containers-form__input--short"
                type="number"
                min={10}
                max={3600}
                value={scalingPolicy.cooldown_seconds}
                onChange={(event) =>
                  patch({
                    cooldown_seconds: parseInt(event.target.value, 10) || 60,
                  })
                }
              />
              <p className="containers-muted containers-form__hint">
                Minimum seconds between scale-up or scale-down actions.
              </p>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
