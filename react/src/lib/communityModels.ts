// 社区版模型筛选模块：隐藏需要 Jaaz 账号的云端模型。
export function filterJaazCloudModels<T extends { provider?: string }>(
  models: T[] | undefined
): T[] {
  return (models ?? []).filter((model) => model.provider !== 'jaaz')
}
