import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render } from '@testing-library/react'
import L from 'leaflet'
import { LeafletMap, type MapMarker } from './LeafletMap'

afterEach(cleanup)

const marker = (over: Partial<MapMarker> = {}): MapMarker => ({
  key: 'm1',
  lat: 38.9,
  lon: -77.03,
  radius: 7,
  color: '#22c55e',
  fillOpacity: 0.8,
  popup: { strong: true, lines: ['Gate B motion', 'event'] },
  ...over,
})

describe('LeafletMap', () => {
  it('reports the initial view so the page can query the backend for it', () => {
    const onViewChange = vi.fn()
    render(<LeafletMap center={[38.9, -77.03]} zoom={13} tileUrl="https://tiles.example.org/{z}/{x}/{y}.png" attribution="x" markers={[]} onViewChange={onViewChange} />)
    expect(onViewChange).toHaveBeenCalledTimes(1)
    expect(onViewChange.mock.calls[0][0]).toMatchObject({ zoom: 13 })
  })

  it('renders one circle marker per marker and redraws when markers change', () => {
    const spy = vi.spyOn(L, 'circleMarker')
    const props = { center: [38.9, -77.03] as [number, number], zoom: 13, tileUrl: 'https://t/{z}/{x}/{y}.png', attribution: 'x', onViewChange: () => {} }
    const { rerender } = render(<LeafletMap {...props} markers={[marker()]} />)
    expect(spy).toHaveBeenCalledTimes(1)
    rerender(<LeafletMap {...props} markers={[marker({ key: 'a' }), marker({ key: 'b', lat: 38.91 })]} />)
    expect(spy).toHaveBeenCalledTimes(3)
  })

  it('puts record text into popups as text, never as HTML', () => {
    const spy = vi.spyOn(L.CircleMarker.prototype, 'bindPopup')
    const hostile = '<img src=x onerror="window.__xss=1">'
    render(
      <LeafletMap center={[38.9, -77.03]} zoom={13} tileUrl="https://t/{z}/{x}/{y}.png" attribution="x" onViewChange={() => {}}
        markers={[marker({ popup: { strong: true, lines: [hostile, 'event'], note: 'Synthetic demonstration data' } })]} />,
    )
    const content = spy.mock.calls[0][0] as HTMLElement
    expect(content).toBeInstanceOf(HTMLElement)
    expect(content.querySelector('img')).toBeNull()
    expect(content.textContent).toContain(hostile)
    expect(content.querySelector('.font-semibold')?.textContent).toBe(hostile)
    expect(content.textContent).toContain('Synthetic demonstration data')
  })

  it('wires popup action buttons to their handler', () => {
    const spy = vi.spyOn(L.CircleMarker.prototype, 'bindPopup')
    const onAction = vi.fn()
    render(
      <LeafletMap center={[38.9, -77.03]} zoom={13} tileUrl="https://t/{z}/{x}/{y}.png" attribution="x" onViewChange={() => {}}
        markers={[marker({ popup: { lines: ['3 records'], action: { label: 'List members below', onClick: onAction } } })]} />,
    )
    const content = spy.mock.calls[0][0] as HTMLElement
    content.querySelector('button')!.click()
    expect(onAction).toHaveBeenCalledTimes(1)
  })
})
