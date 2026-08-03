/**
 * Test Information Function (TIF) Chart
 *
 * Displays the total test information across the ability range.
 * Higher information means more precise measurement at that ability level.
 */

import { useEffect, useRef } from 'react'
import * as d3 from 'd3'
import type { TIFDataPoint } from '../../api/types'

interface TIFChartProps {
  data: TIFDataPoint[]
  peakTheta?: number
  peakInformation?: number
  coverageLow?: number
  coverageHigh?: number
  width?: number
  height?: number
  showSE?: boolean
  reliabilityThreshold?: number
}

export default function TIFChart({
  data,
  peakTheta,
  peakInformation,
  coverageLow = -2,
  coverageHigh = 2,
  width = 600,
  height = 350,
  showSE = true,
  reliabilityThreshold,
}: TIFChartProps) {
  const svgRef = useRef<SVGSVGElement>(null)

  useEffect(() => {
    if (!svgRef.current || !data.length) return

    // Clear previous content
    d3.select(svgRef.current).selectAll('*').remove()

    // Margins
    const margin = { top: 30, right: showSE ? 70 : 30, bottom: 50, left: 60 }
    const innerWidth = width - margin.left - margin.right
    const innerHeight = height - margin.top - margin.bottom

    // Create SVG
    const svg = d3
      .select(svgRef.current)
      .attr('width', width)
      .attr('height', height)

    const g = svg
      .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`)

    // Scales
    const xScale = d3
      .scaleLinear()
      .domain([-4, 4])
      .range([0, innerWidth])

    const maxInfo = d3.max(data, (d) => d.information) || 10
    const yScaleInfo = d3
      .scaleLinear()
      .domain([0, maxInfo * 1.1])
      .range([innerHeight, 0])

    // Standard error scale (inverse of sqrt(info))
    const maxSE = d3.max(data, (d) => d.standard_error) || 1
    const yScaleSE = d3
      .scaleLinear()
      .domain([0, Math.min(maxSE * 1.2, 2)])
      .range([innerHeight, 0])

    // Grid lines
    g.append('g')
      .attr('class', 'grid')
      .attr('transform', `translate(0,${innerHeight})`)
      .call(
        d3.axisBottom(xScale)
          .tickSize(-innerHeight)
          .tickFormat(() => '')
      )
      .selectAll('line')
      .attr('stroke', '#e5e7eb')
      .attr('stroke-dasharray', '2,2')

    g.append('g')
      .attr('class', 'grid')
      .call(
        d3.axisLeft(yScaleInfo)
          .tickSize(-innerWidth)
          .tickFormat(() => '')
      )
      .selectAll('line')
      .attr('stroke', '#e5e7eb')
      .attr('stroke-dasharray', '2,2')

    g.selectAll('.grid .domain').remove()

    // Axes
    g.append('g')
      .attr('transform', `translate(0,${innerHeight})`)
      .call(d3.axisBottom(xScale).ticks(8))
      .selectAll('text')
      .attr('fill', '#374151')

    g.append('g')
      .call(d3.axisLeft(yScaleInfo).ticks(6).tickFormat(d3.format('.1f')))
      .selectAll('text')
      .attr('fill', '#374151')

    // Secondary y-axis for SE
    if (showSE) {
      g.append('g')
        .attr('transform', `translate(${innerWidth},0)`)
        .call(d3.axisRight(yScaleSE).ticks(5).tickFormat(d3.format('.2f')))
        .selectAll('text')
        .attr('fill', '#f59e0b')
    }

    // Axis labels
    g.append('text')
      .attr('x', innerWidth / 2)
      .attr('y', innerHeight + 40)
      .attr('text-anchor', 'middle')
      .attr('fill', '#374151')
      .attr('font-size', '12px')
      .text('Ability (θ)')

    g.append('text')
      .attr('transform', 'rotate(-90)')
      .attr('x', -innerHeight / 2)
      .attr('y', -45)
      .attr('text-anchor', 'middle')
      .attr('fill', '#374151')
      .attr('font-size', '12px')
      .text('Information')

    if (showSE) {
      g.append('text')
        .attr('transform', 'rotate(90)')
        .attr('x', innerHeight / 2)
        .attr('y', -innerWidth - 50)
        .attr('text-anchor', 'middle')
        .attr('fill', '#f59e0b')
        .attr('font-size', '12px')
        .text('Standard Error')
    }

    // Coverage region highlight
    const coverageData = data.filter(
      (d) => d.theta >= coverageLow && d.theta <= coverageHigh
    )

    if (coverageData.length > 0) {
      const areaCoverage = d3
        .area<TIFDataPoint>()
        .x((d) => xScale(d.theta))
        .y0(innerHeight)
        .y1((d) => yScaleInfo(d.information))
        .curve(d3.curveMonotoneX)

      g.append('path')
        .datum(coverageData)
        .attr('fill', '#3b82f622')
        .attr('d', areaCoverage)

      // Coverage boundary lines
      g.append('line')
        .attr('x1', xScale(coverageLow))
        .attr('x2', xScale(coverageLow))
        .attr('y1', 0)
        .attr('y2', innerHeight)
        .attr('stroke', '#9ca3af')
        .attr('stroke-width', 1)
        .attr('stroke-dasharray', '3,3')

      g.append('line')
        .attr('x1', xScale(coverageHigh))
        .attr('x2', xScale(coverageHigh))
        .attr('y1', 0)
        .attr('y2', innerHeight)
        .attr('stroke', '#9ca3af')
        .attr('stroke-width', 1)
        .attr('stroke-dasharray', '3,3')
    }

    // TIF Line
    const lineInfo = d3
      .line<TIFDataPoint>()
      .x((d) => xScale(d.theta))
      .y((d) => yScaleInfo(d.information))
      .curve(d3.curveMonotoneX)

    g.append('path')
      .datum(data)
      .attr('fill', 'none')
      .attr('stroke', '#3b82f6')
      .attr('stroke-width', 2.5)
      .attr('d', lineInfo)

    // SE curve (if shown)
    if (showSE) {
      const lineSE = d3
        .line<TIFDataPoint>()
        .x((d) => xScale(d.theta))
        .y((d) => yScaleSE(d.standard_error))
        .curve(d3.curveMonotoneX)

      g.append('path')
        .datum(data)
        .attr('fill', 'none')
        .attr('stroke', '#f59e0b')
        .attr('stroke-width', 2)
        .attr('stroke-dasharray', '5,3')
        .attr('d', lineSE)
    }

    // Peak marker
    if (peakTheta !== undefined && peakInformation !== undefined) {
      g.append('circle')
        .attr('cx', xScale(peakTheta))
        .attr('cy', yScaleInfo(peakInformation))
        .attr('r', 5)
        .attr('fill', '#3b82f6')
        .attr('stroke', '#fff')
        .attr('stroke-width', 2)

      g.append('text')
        .attr('x', xScale(peakTheta) + 10)
        .attr('y', yScaleInfo(peakInformation) - 10)
        .attr('fill', '#374151')
        .attr('font-size', '10px')
        .text(`Peak: (${peakTheta.toFixed(2)}, ${peakInformation.toFixed(2)})`)
    }

    // Reliability threshold line
    if (reliabilityThreshold !== undefined) {
      // Convert reliability to information: I = r / (1 - r) approximately
      const infoThreshold = reliabilityThreshold / (1 - reliabilityThreshold)

      if (infoThreshold < maxInfo * 1.1) {
        g.append('line')
          .attr('x1', 0)
          .attr('x2', innerWidth)
          .attr('y1', yScaleInfo(infoThreshold))
          .attr('y2', yScaleInfo(infoThreshold))
          .attr('stroke', '#ef4444')
          .attr('stroke-width', 1.5)
          .attr('stroke-dasharray', '6,3')

        g.append('text')
          .attr('x', 5)
          .attr('y', yScaleInfo(infoThreshold) - 5)
          .attr('fill', '#ef4444')
          .attr('font-size', '10px')
          .text(`r = ${reliabilityThreshold.toFixed(2)} threshold`)
      }
    }

    // Title
    svg
      .append('text')
      .attr('x', width / 2)
      .attr('y', 20)
      .attr('text-anchor', 'middle')
      .attr('font-size', '14px')
      .attr('font-weight', '600')
      .attr('fill', '#111827')
      .text('Test Information Function')

  }, [data, peakTheta, peakInformation, coverageLow, coverageHigh, width, height, showSE, reliabilityThreshold])

  // Calculate some summary stats
  const avgInfoInCoverage = data
    .filter((d) => d.theta >= coverageLow && d.theta <= coverageHigh)
    .reduce((sum, d) => sum + d.information, 0) /
    data.filter((d) => d.theta >= coverageLow && d.theta <= coverageHigh).length || 0

  return (
    <div className="relative">
      <svg ref={svgRef}></svg>

      {/* Legend */}
      <div className="absolute bottom-2 left-16 flex gap-4 text-xs">
        <div className="flex items-center gap-1">
          <div className="w-4 h-0.5 bg-blue-500"></div>
          <span className="text-gray-600">Information</span>
        </div>
        {showSE && (
          <div className="flex items-center gap-1">
            <div className="w-4 h-0.5 bg-amber-500" style={{ borderStyle: 'dashed' }}></div>
            <span className="text-gray-600">Standard Error</span>
          </div>
        )}
        <div className="flex items-center gap-1">
          <div className="w-4 h-2 bg-blue-500/20"></div>
          <span className="text-gray-600">Coverage ({coverageLow} to {coverageHigh})</span>
        </div>
      </div>

      {/* Summary stats */}
      <div className="absolute top-8 right-4 text-xs bg-white/90 px-3 py-2 rounded border border-gray-200">
        {peakTheta !== undefined && (
          <div>Peak θ: {peakTheta.toFixed(2)}</div>
        )}
        {peakInformation !== undefined && (
          <div>Peak Info: {peakInformation.toFixed(2)}</div>
        )}
        <div className="mt-1 pt-1 border-t border-gray-100">
          Avg Info (coverage): {avgInfoInCoverage.toFixed(2)}
        </div>
      </div>
    </div>
  )
}

/**
 * Generate TIF data by summing item information functions.
 */
export function generateTIFData(
  itemParams: Array<{ discrimination: number; difficulty: number; guessing?: number }>,
  thetaRange: [number, number] = [-4, 4],
  numPoints: number = 81
): TIFDataPoint[] {
  const points: TIFDataPoint[] = []
  const step = (thetaRange[1] - thetaRange[0]) / (numPoints - 1)

  for (let i = 0; i < numPoints; i++) {
    const theta = thetaRange[0] + i * step
    let totalInfo = 0

    for (const item of itemParams) {
      const a = item.discrimination
      const b = item.difficulty
      const c = item.guessing || 0

      // Calculate probability
      const exp_val = Math.exp(-a * (theta - b))
      const P = c + (1 - c) / (1 + exp_val)

      // Calculate item information
      if (P > c && P < 1) {
        const info = (a * a * Math.pow(P - c, 2) * (1 - P)) / (Math.pow(1 - c, 2) * P)
        totalInfo += info
      }
    }

    // Standard error is 1 / sqrt(information)
    const standardError = totalInfo > 0 ? 1 / Math.sqrt(totalInfo) : 999

    points.push({
      theta,
      information: totalInfo,
      standard_error: standardError,
    })
  }

  return points
}
