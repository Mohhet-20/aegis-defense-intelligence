import { describe, expect, it } from 'vitest'
import { groupForPath, NAV_GROUPS, visibleGroups } from './navigation'

const allTargets = (groups: typeof NAV_GROUPS) => groups.flatMap((g) => g.items.map((i) => i.to))
const adminOnly = NAV_GROUPS.flatMap((g) => g.items).filter((i) => i.adminOnly).map((i) => i.to)

describe('visibleGroups', () => {
  it('shows administrator-only pages to administrators', () => {
    expect(allTargets(visibleGroups('administrator'))).toEqual(expect.arrayContaining(adminOnly))
  })

  it.each(['analyst', 'investigator', 'viewer', undefined])('hides administrator-only pages from %s', (role) => {
    const targets = allTargets(visibleGroups(role))
    expect(adminOnly.length).toBeGreaterThan(0)
    for (const t of adminOnly) expect(targets).not.toContain(t)
    expect(targets).toContain('/health') // the non-admin item in the Administration group stays
  })

  it('never returns an empty group', () => {
    for (const role of ['administrator', 'viewer']) {
      for (const g of visibleGroups(role)) expect(g.items.length).toBeGreaterThan(0)
    }
  })
})

describe('groupForPath', () => {
  it.each([
    ['/events', 'Data operations'],
    ['/events/123', 'Data operations'],
    ['/cv/jobs/abc', 'Computer vision & tracking'],
    ['/fusion/assessments/xyz', 'Investigations & fusion'],
    ['/mlops/models/1', 'Models & evaluation'],
    ['/admin/security', 'Administration'],
  ])('%s belongs to %s', (path, group) => {
    expect(groupForPath(path)).toBe(group)
  })

  it('does not match on a shared prefix that is not a path segment', () => {
    // "/cv" must not claim "/cvx"; "/events" must not claim "/eventsfoo".
    expect(groupForPath('/cvx')).toBeUndefined()
    expect(groupForPath('/eventsfoo')).toBeUndefined()
  })

  it('returns undefined for the overview and unknown paths', () => {
    expect(groupForPath('/')).toBeUndefined()
    expect(groupForPath('/no-such-page')).toBeUndefined()
  })
})

describe('NAV_GROUPS', () => {
  it('has no duplicate targets', () => {
    const targets = allTargets(NAV_GROUPS)
    expect(new Set(targets).size).toBe(targets.length)
  })
})
