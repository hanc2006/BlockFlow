/**
 * sgs-ui-fmy: tests for the small icon + tooltip that surfaces preset
 * author recommendations next to the ComfyGen block's "Current workflow"
 * line. The trigger is an icon; the tooltip splits recommendations into
 * two clearly-labeled sections (workflow-scoped first, then global) and
 * renders nothing at all when neither scope has entries.
 */
import { describe, expect, test } from 'vitest'
import { render, screen } from '@testing-library/react'
import { TooltipProvider } from '@/components/ui/tooltip'
import {
  PresetRecommendationsBody,
  PresetRecommendationsTooltip,
} from './preset-recommendations-tooltip'

function renderWithProvider(node: React.ReactNode) {
  // delayDuration=0 so the tooltip content is reachable in tests without
  // chasing async hover delays — RTL queries the trigger and content
  // independently via aria roles.
  return render(<TooltipProvider delayDuration={0}>{node}</TooltipProvider>)
}

describe('PresetRecommendationsTooltip', () => {
  test('renders nothing when both scopes are empty', () => {
    const { container } = renderWithProvider(
      <PresetRecommendationsTooltip
        workflowName="Replace Face"
        globalRecs={[]}
        workflowRecs={[]}
      />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  test('renders the trigger when global recommendations exist', () => {
    renderWithProvider(
      <PresetRecommendationsTooltip
        workflowName="Replace Face"
        globalRecs={['Pairs best with a character LoRA']}
        workflowRecs={[]}
      />,
    )
    expect(
      screen.getByRole('button', { name: /preset recommendations/i }),
    ).toBeInTheDocument()
  })

  test('renders the trigger when workflow-scoped recommendations exist', () => {
    renderWithProvider(
      <PresetRecommendationsTooltip
        workflowName="Replace Face"
        globalRecs={[]}
        workflowRecs={['Bump mask coverage for tight crops']}
      />,
    )
    expect(
      screen.getByRole('button', { name: /preset recommendations/i }),
    ).toBeInTheDocument()
  })

  test('body shows workflow-scoped section labeled with workflow name', () => {
    render(
      <PresetRecommendationsBody
        workflowName="Replace Face"
        globalRecs={[]}
        workflowRecs={['Bump mask coverage for tight crops']}
      />,
    )
    expect(screen.getByText('For Replace Face')).toBeInTheDocument()
    expect(screen.getByText(/bump mask coverage/i)).toBeInTheDocument()
  })

  test('body shows General section for global recs only', () => {
    render(
      <PresetRecommendationsBody
        workflowName="Replace Face"
        globalRecs={['Pairs best with a character LoRA']}
        workflowRecs={[]}
      />,
    )
    expect(screen.getByText('General')).toBeInTheDocument()
    expect(screen.getByText(/character lora/i)).toBeInTheDocument()
    expect(screen.queryByText('For Replace Face')).not.toBeInTheDocument()
  })

  test('body shows both sections, workflow-scoped first', () => {
    render(
      <PresetRecommendationsBody
        workflowName="Replace Face"
        globalRecs={['Pairs best with a character LoRA']}
        workflowRecs={['Bump mask coverage for tight crops']}
      />,
    )
    const workflowHeader = screen.getByText('For Replace Face')
    const globalHeader = screen.getByText('General')
    expect(workflowHeader).toBeInTheDocument()
    expect(globalHeader).toBeInTheDocument()
    // DOM order: workflow section comes before the general section.
    const pos = workflowHeader.compareDocumentPosition(globalHeader)
    // eslint-disable-next-line no-bitwise
    expect(pos & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  test('renders multiple items in a section', () => {
    render(
      <PresetRecommendationsBody
        workflowName="Replace Face"
        globalRecs={['one', 'two', 'three']}
        workflowRecs={[]}
      />,
    )
    expect(screen.getByText('one')).toBeInTheDocument()
    expect(screen.getByText('two')).toBeInTheDocument()
    expect(screen.getByText('three')).toBeInTheDocument()
  })
})
