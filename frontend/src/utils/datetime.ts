/** API 时间是否已经携带 UTC 或明确的数字时区。 */
const TIME_ZONE_SUFFIX = /(?:Z|[+-]\d{2}:?\d{2})$/i;

/**
 * 解析后端业务时间。
 *
 * 新版接口统一返回带 Z 的 UTC 时间；这里继续兼容旧接口和旧缓存中的 UTC 裸值，
 * 防止前后端滚动更新期间浏览器把它们错误解释为本地时间。日期型业务字段不调用
 * 此函数，避免给“报告周期”这类纯日期附加不必要的时区。
 */
export function parseApiDateTime(value: string): Date {
  const normalized = value.trim();
  if (!normalized) return new Date(Number.NaN);
  return new Date(TIME_ZONE_SUFFIX.test(normalized) ? normalized : `${normalized}Z`);
}

/** 按浏览器本地时区格式化 API 时间，非法值返回空字符串。 */
export function formatApiDateTime(
  value: string | null | undefined,
  options?: Intl.DateTimeFormatOptions,
): string {
  if (!value) return "";
  const date = parseApiDateTime(value);
  if (Number.isNaN(date.getTime())) return "";
  return options
    ? new Intl.DateTimeFormat("zh-CN", options).format(date)
    : date.toLocaleString("zh-CN");
}
