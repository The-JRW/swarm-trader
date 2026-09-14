import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Loader2, LucideIcon, Plus } from "lucide-react";
import { useState } from "react";

interface ComponentItemProps {
  icon: LucideIcon;
  label: string;
  onClick?: () => void;
  className?: string;
  isActive?: boolean;
  disabled?: boolean;
  mounting?: boolean;
}

export default function ComponentItem({ 
  icon: Icon, 
  label, 
  onClick, 
  className, 
  isActive = false,
  disabled = false,
  mounting = false,
}: ComponentItemProps) {
  const [isHovered, setIsHovered] = useState(false);
  
  const handlePlusClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (disabled || mounting) return;
    if (onClick) onClick();
  };

  const handleClick = () => {
    if (disabled || mounting) return;
    if (onClick) onClick();
  };
  
  return (
    <div 
      className={cn(
        "group flex items-center gap-2 px-2 py-1.5 rounded-md text-subtitle transition-colors duration-150",
        disabled || mounting ? "opacity-50 cursor-not-allowed" : "cursor-pointer",
        isActive ? "bg-ramp-grey-700 text-primary" : "text-primary",
        isHovered && !disabled && !mounting ? "hover-bg" : "",
        className
      )}
      onClick={handleClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      role="button"
      tabIndex={disabled || mounting ? -1 : 0}
      aria-disabled={disabled || mounting}
      onKeyDown={(e) => {
        if (e.key === 'Enter') handleClick();
      }}
    >
      <div className="flex-shrink-0">
        <Icon size={16} className={isActive ? "text-primary" : "text-muted-foreground"} />
      </div>
      <span className="truncate">{label}</span>
      
      <div className="ml-auto opacity-0 group-hover:opacity-100">
        <Button
          variant="ghost"
          size="icon"
          className="h-5 w-5 hover-bg hover:text-primary text-muted-foreground flex items-center justify-center"
          onClick={handlePlusClick}
          disabled={disabled || mounting}
          aria-label="Add"
        >
          {mounting ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
        </Button>
      </div>
    </div>
  );
}
