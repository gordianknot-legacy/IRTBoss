/**
 * Item Characteristic Curve (ICC) Chart
 *
 * Displays the probability of correct response as a function of ability (theta).
 * The ICC is fundamental to IRT and shows how item parameters affect response probability.
 */

import { useEffect, useRef } from 'react'
import * as d3 from 'd3'
import type { ICCDataPoint } from '../../api/types'

interface ICCChartProps {
  data: ICCDataPoint[]
  itemId: string
  difficulty: number
  discrimination: number
  guessing?: number
  width?: number
  height?: number
  showInformation?: boolean
}

export default function ICCChart({
  data,
  itemId,
  difficulty,
  discrimination,
  guessing = 0,
  width = 500,
  height = 350,
  showInformation = false,
}: ICCChartProps) {
  const svgRef = useRef<SVGSVGElement>(null)

  useEffect(() => {
    if (!svgRef.current || !data.length) return

    // Clear previous content
    d3.select(svgRef.current).selectAll('*').remove()

    // Margins
    const margin = { top: 30, right: 60, bottom: 50, left: 60 }
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

    const yScaleProb = d3
      .scaleLinear()
      .domain([0, 1])
      .range([innerHeight, 0])

    // Information scale (secondary y-axis)
    const maxInfo = d3.max(data, (d) => d.information) || 1
    const yScaleInfo = d3
      .scaleLinear()
      .domain([0, maxInfo * 1.1])
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
        d3.axisLeft(yScaleProb)
          .tickSize(-innerWidth)
          .tickFormat(() => '')
      )
      .selectAll('line')
      .attr('stroke', '#e5e7eb')
      .attr('stroke-dasharray', '2,2')

    // Remove domain lines from grid
    g.selectAll('.grid .domain').remove()

    // Axes
    g.append('g')
      .attr('transform', `translate(0,${innerHeight})`)
      .call(d3.axisBottom(xScale).ticks(8))
      .selectAll('text')
      .attr('fill', '#374151')

    g.append('g')
      .call(d3.axisLeft(yScaleProb).ticks(5).tickFormat(d3.format('.1f')))
      .selectAll('text')
      .attr('fill', '#374151')

    // Secondary y-axis for information (if shown)
    if (showInformation) {
      g.append('g')
        .attr('transform', `translate(${innerWidth},0)`)
        .call(d3.axisRight(yScaleInfo).ticks(5).tickFormat(d3.format('.2f')))
        .selectAll('text')
        .attr('fill', '#10b981')
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
      .text('P(correct)')

    if (showInformation) {
      g.append('text')
        .attr('transform', 'rotate(90)')
        .attr('x', innerHeight / 2)
        .attr('y', -innerWidth - 45)
        .attr('text-anchor', 'middle')
        .attr('fill', '#10b981')
        .attr('font-size', '12px')
        .text('Information')
    }

    // ICC Line
    const lineProb = d3
      .line<ICCDataPoint>()
      .x((d) => xScale(d.theta))
      .y((d) => yScaleProb(d.probability))
      .curve(d3.curveMonotoneX)

    g.append('path')
      .datum(data)
      .attr('fill', 'none')
      .attr('stroke', '#3b82f6')
      .attr('stroke-width', 2.5)
      .attr('d', lineProb)

    // Information curve (if shown)
    if (showInformation) {
      const lineInfo = d3
        .line<ICCDataPoint>()
        .x((d) => xScale(d.theta))
        .y((d) => yScaleInfo(d.information))
        .curve(d3.curveMonotoneX)

      // Area under information curve
      const areaInfo = d3
        .area<ICCDataPoint>()
        .x((d) => xScale(d.theta))
        .y0(innerHeight)
        .y1((d) => yScaleInfo(d.information))
        .curve(d3.curveMonotoneX)

      g.append('path')
        .datum(data)
        .attr('fill', '#10b98133')
        .attr('d', areaInfo)

      g.append('path')
        .datum(data)
        .attr('fill', 'none')
        .attr('stroke', '#10b981')
        .attr('stroke-width', 2)
        .attr('stroke-dasharray', '5,3')
        .attr('d', lineInfo)
    }

    // Difficulty marker (vertical line at b parameter)
    g.append('line')
      .attr('x1', xScale(difficulty))
      .attr('x2', xScale(difficulty))
      .attr('y1', 0)
      .attr('y2', innerHeight)
      .attr('stroke', '#ef4444')
      .attr('stroke-width', 1.5)
      .attr('stroke-dasharray', '4,4')

    // Horizontal line at P = 0.5 (or P = (1+c)/2 for 3PL)
    const pAtDifficulty = guessing + (1 - guessing) * 0.5
    g.append('line')
      .attr('x1', 0)
      .attr('x2', xScale(difficulty))
      .attr('y1', yScaleProb(pAtDifficulty))
      .attr('y2', yScaleProb(pAtDifficulty))
      .attr('stroke', '#9ca3af')
      .attr('stroke-width', 1)
      .attr('stroke-dasharray', '2,2')

    // Guessing asymptote (if c > 0)
    if (guessing > 0.01) {
      g.append('line')
        .attr('x1', 0)
        .attr('x2', innerWidth)
        .attr('y1', yScaleProb(guessing))
        .attr('y2', yScaleProb(guessing))
        .attr('stroke', '#f59e0b')
        .attr('stroke-width', 1)
        .attr('stroke-dasharray', '3,3')

      g.append('text')
        .attr('x', innerWidth - 5)
        .attr('y', yScaleProb(guessing) - 5)
        .attr('text-anchor', 'end')
        .attr('fill', '#f59e0b')
        .attr('font-size', '10px')
        .text(`c = ${guessing.toFixed(2)}`)
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
      .text(`Item Characteristic Curve: ${itemId}`)

  }, [data, itemId, difficulty, discrimination, guessing, width, height, showInformation])

  return (
    <div className="relative">
      <svg ref={svgRef}></svg>

      {/* Legend */}
      <div className="absolute bottom-2 left-16 flex gap-4 text-xs">
        <div className="flex items-center gap-1">
          <div className="w-4 h-0.5 bg-blue-500"></div>
          <span className="text-gray-600">P(correct)</span>
        </div>
        {showInformation && (
          <div className="flex items-center gap-1">
            <div className="w-4 h-0.5 bg-emerald-500" style={{ borderStyle: 'dashed' }}></div>
            <span className="text-gray-600">Information</span>
          </div>
        )}
        <div className="flex items-center gap-1">
          <div className="w-4 h-0.5 bg-red-500" style={{ borderStyle: 'dashed' }}></div>
          <span className="text-gray-600">Difficulty (b={difficulty.toFixed(2)})</span>
        </div>
      </div>

      {/* Parameters */}
      <div className="absolute top-8 right-4 text-xs bg-white/90 px-2 py-1 rounded border border-gray-200">
        <div>a = {discrimination.toFixed(2)}</div>
        <div>b = {difficulty.toFixed(2)}</div>
        {guessing > 0.01 && <div>c = {guessing.toFixed(2)}</div>}
      </div>
    </div>
  )
}

/**
 * Generate ICC data points from item parameters.
 * Useful for generating mock data or computing ICC from parameters.
 */
export function generateICCData(
  discrimination: number,
  difficulty: number,
  guessing: number = 0,
  thetaRange: [number, number] = [-4, 4],
  numPoints: number = 81
): ICCDataPoint[] {
  const points: ICCDataPoint[] = []
  const step = (thetaRange[1] - thetaRange[0]) / (numPoints - 1)

  for (let i = 0; i < numPoints; i++) {
    const theta = thetaRange[0] + i * step
    // 3PL model: P(theta) = c + (1-c) / (1 + exp(-a(theta - b)))
    const exp_val = Math.exp(-discrimination * (theta - difficulty))
    const probability = guessing + (1 - guessing) / (1 + exp_val)
    // Item information: I(theta) = a^2 * (P - c)^2 * (1 - P) / ((1 - c)^2 * P)
    const P = probability
    const a = discrimination
    const c = guessing
    let information = 0
    if (P > c && P < 1) {
      information = (a * a * Math.pow(P - c, 2) * (1 - P)) / (Math.pow(1 - c, 2) * P)
    }

    points.push({ theta, probability, information })
  }

  return points
}
