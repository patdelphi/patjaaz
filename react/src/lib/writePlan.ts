/** 程序说明：安全解析 write_plan 输入，并过滤不符合结构的步骤。 */
export type WritePlanStep = {
  title: string
  description: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function parseWritePlanSteps(args: unknown): WritePlanStep[] {
  let parsed: unknown = args

  if (typeof args === 'string') {
    try {
      parsed = JSON.parse(args)
    } catch {
      return []
    }
  }

  if (!isRecord(parsed) || !Array.isArray(parsed.steps)) return []

  return parsed.steps
    .filter(
      (step): step is Record<string, unknown> =>
        isRecord(step) && typeof step.title === 'string'
    )
    .map((step) => ({
      title: step.title as string,
      description:
        typeof step.description === 'string' ? step.description : '',
    }))
}