type StatCardProps = {
  label: string;
  value: string | number;
  icon: string;
  subtitle?: string;
};

export function StatCard({ label, value, icon, subtitle }: StatCardProps) {
  return (
    <div className="bg-card rounded-xl p-5 border border-border shadow-sahara flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground text-sm font-medium">
          {label}
        </span>
        <span className="material-symbols-outlined text-primary-foreground bg-[var(--sahara-container)] p-2 rounded-lg text-base">
          {icon}
        </span>
      </div>
      <div>
        <div className="text-3xl tracking-tight text-foreground font-heading">
          {value}
        </div>
        {subtitle && (
          <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>
        )}
      </div>
    </div>
  );
}
