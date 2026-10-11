import { SALARY_PERIOD_LABELS, type JobDetail } from "./types";

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

export function formatDate(iso: string): string {
  return dateFormat.format(new Date(iso));
}

/** "INR 8,00,000 – 12,00,000 per year", or as much of that as was given; "" if no salary. */
export function formatSalary(job: JobDetail): string {
  const { salary_min: low, salary_max: high } = job;
  if (low === null && high === null) {
    return "";
  }
  const amount = (value: number) => value.toLocaleString();
  const range =
    low !== null && high !== null && low !== high
      ? `${amount(low)} – ${amount(high)}`
      : low !== null && high === null
        ? `from ${amount(low)}`
        : high !== null && low === null
          ? `up to ${amount(high)}`
          : amount(low ?? high ?? 0);
  const period = job.salary_period ? SALARY_PERIOD_LABELS[job.salary_period] : "";
  return [job.salary_currency, range, period].filter(Boolean).join(" ");
}
