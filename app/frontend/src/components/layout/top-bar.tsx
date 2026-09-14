import { PerformanceDashboard } from '@/components/layout/performance-dashboard';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { PanelBottom, PanelLeft, PanelRight, Settings, Sparkles } from 'lucide-react';

interface TopBarProps {
  isLeftCollapsed: boolean;
  isRightCollapsed: boolean;
  isBottomCollapsed: boolean;
  onToggleLeft: () => void;
  onToggleRight: () => void;
  onToggleBottom: () => void;
  onSettingsClick: () => void;
  onStrategiesClick?: () => void;
}

export function TopBar({
  isLeftCollapsed,
  isRightCollapsed,
  isBottomCollapsed,
  onToggleLeft,
  onToggleRight,
  onToggleBottom,
  onSettingsClick,
  onStrategiesClick,
}: TopBarProps) {
  return (
    <div className="absolute top-0 left-0 right-0 z-40 flex items-center justify-between gap-2 py-1 px-2 bg-panel/90 border-b border-ramp-grey-800/60 backdrop-blur-sm pointer-events-none">
      <div className="pointer-events-auto min-w-0 flex-1">
        <PerformanceDashboard />
      </div>

      <div className="pointer-events-auto flex items-center gap-0 shrink-0">
        {onStrategiesClick && (
          <>
            <Button
              variant="ghost"
              size="sm"
              onClick={onStrategiesClick}
              className="h-8 px-2 gap-1 text-muted-foreground hover:text-foreground hover:bg-ramp-grey-700 transition-colors"
              aria-label="Open Strategies"
              title="Strategies — paper analysis"
            >
              <Sparkles size={14} />
              <span className="text-xs hidden sm:inline">Strategies</span>
            </Button>
            <div className="w-px h-5 bg-ramp-grey-700 mx-1" />
          </>
        )}

        <Button
          variant="ghost"
          size="sm"
          onClick={onToggleLeft}
          className={cn(
            "h-8 w-8 p-0 text-muted-foreground hover:text-foreground hover:bg-ramp-grey-700 transition-colors",
            !isLeftCollapsed && "text-foreground"
          )}
          aria-label="Toggle left sidebar"
          title="Toggle Left Side Bar (⌘B)"
        >
          <PanelLeft size={16} />
        </Button>

        <Button
          variant="ghost"
          size="sm"
          onClick={onToggleBottom}
          className={cn(
            "h-8 w-8 p-0 text-muted-foreground hover:text-foreground hover:bg-ramp-grey-700 transition-colors",
            !isBottomCollapsed && "text-foreground"
          )}
          aria-label="Toggle bottom panel"
          title="Toggle Bottom Panel (⌘J)"
        >
          <PanelBottom size={16} />
        </Button>

        <Button
          variant="ghost"
          size="sm"
          onClick={onToggleRight}
          className={cn(
            "h-8 w-8 p-0 text-muted-foreground hover:text-foreground hover:bg-ramp-grey-700 transition-colors",
            !isRightCollapsed && "text-foreground"
          )}
          aria-label="Toggle right sidebar"
          title="Toggle Right Side Bar (⌘I)"
        >
          <PanelRight size={16} />
        </Button>

        <div className="w-px h-5 bg-ramp-grey-700 mx-1" />

        <Button
          variant="ghost"
          size="sm"
          onClick={onSettingsClick}
          className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground hover:bg-ramp-grey-700 transition-colors"
          aria-label="Open settings"
          title="Open Settings (⌘,)"
        >
          <Settings size={16} />
        </Button>
      </div>
    </div>
  );
}
