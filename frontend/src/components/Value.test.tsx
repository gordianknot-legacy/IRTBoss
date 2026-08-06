/**
 * The rendering half of the absence guarantee.
 *
 * `lib/absence.test.ts` proves the data layer never turns a null into a
 * numeral; these assert that the component layer never turns it into a blank
 * either — a cell that renders empty is exactly as wrong as one that renders 0.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { NumCell, Stat, Value } from './Value'
import { present, presentCount } from '@/lib/absence'

describe('<Value>', () => {
  it('renders an absent value as visible text, not an empty node', () => {
    const { container } = render(<Value presented={present(null)} />)
    expect(container.textContent).toContain('not computed')
    expect(container.textContent?.trim()).not.toBe('')
  })

  it('marks absence in the DOM so it is distinguishable from a value', () => {
    const { container } = render(<Value presented={present(null)} />)
    expect(container.querySelector('[data-absent="true"]')).not.toBeNull()
  })

  it('renders zero as a value, not as an absence', () => {
    const { container } = render(<Value presented={present(0)} />)
    expect(container.querySelector('[data-absent="false"]')).not.toBeNull()
    expect(container.textContent).toBe('0.000')
    expect(container.textContent).not.toContain('not computed')
  })

  it('exposes the reason for an absence as a title', () => {
    render(<Value presented={present(null, { reason: 'the test was refused' })} />)
    expect(screen.getByTitle('the test was refused')).toBeTruthy()
  })

  it('gives a default explanation when the payload carried no reason', () => {
    const { container } = render(<Value presented={present(null)} />)
    const title = container.querySelector('[data-absent="true"]')?.getAttribute('title') ?? ''
    expect(title).toContain('not zero')
  })
})

describe('<NumCell>', () => {
  it('never renders an empty table cell for a null', () => {
    const { container } = render(
      <table>
        <tbody>
          <tr>
            <NumCell presented={present(null)} />
          </tr>
        </tbody>
      </table>,
    )
    const cell = container.querySelector('td')
    expect(cell?.textContent?.trim()).not.toBe('')
    expect(cell?.textContent).toContain('not computed')
  })
})

describe('<Stat>', () => {
  it('prints the absence reason as body text rather than hiding it in a tooltip', () => {
    render(
      <Stat
        label="RMSEA₂"
        presented={present(null, { reason: 'too few moments for the number of parameters' })}
      />,
    )
    expect(screen.getByText('too few moments for the number of parameters')).toBeTruthy()
  })

  it('renders a present count without any absence marker', () => {
    const { container } = render(<Stat label="Items" presented={presentCount(12)} />)
    expect(container.textContent).toContain('12')
    expect(container.textContent).not.toContain('not computed')
  })
})
