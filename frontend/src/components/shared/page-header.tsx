type PageHeaderProps = {
  title: string;
  description?: string;
  action?: React.ReactNode;
};

export function PageHeader({ title, description, action }: PageHeaderProps) {
  return (
    <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h2 className="text-3xl lg:text-4xl tracking-tight text-foreground">
          {title}
        </h2>
        {description && (
          <p className="text-muted-foreground text-sm mt-1 max-w-xl">
            {description}
          </p>
        )}
      </div>
      {action && <div className="mt-3 sm:mt-0">{action}</div>}
    </div>
  );
}
