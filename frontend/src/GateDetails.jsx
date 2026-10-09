/* Real gate results (not hard-coded ticks): policy warnings, reviewer concerns, twin check results */
export default function GateDetails({ review, policy, twin }) {
  const warnings = policy?.warnings || []
  const concerns = review?.concerns || []
  const checks = Object.entries(twin?.results || {})
  return (
    <div className="gates">
      <div className="gatesum">
        <span className={policy?.allowed === false ? 'bad' : ''}>{policy?.allowed === false ? '✗' : '✓'} Policy</span>
        <span className={review?.approve === false ? 'bad' : ''}>{review?.approve === false ? '✗' : '✓'} Reviewer</span>
        <span className={twin?.ok === false ? 'bad' : ''}>{twin?.ok === false ? '✗' : '✓'} Twin</span>
      </div>
      {warnings.length > 0 && (
        <ul className="gwarn">{warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}</ul>
      )}
      {concerns.length > 0 && (
        <ul className="gwarn">{concerns.map((c, i) => <li key={i}>Reviewer: {c}</li>)}</ul>
      )}
      {checks.length > 0 && (
        <details className="gchecks">
          <summary>Twin checks ({checks.filter(([, ok]) => ok).length}/{checks.length} passed)</summary>
          {checks.map(([k, ok]) => <div key={k} className={ok ? 'gok' : 'bad'}>{ok ? '✓' : '✗'} {k}</div>)}
        </details>
      )}
    </div>
  )
}

