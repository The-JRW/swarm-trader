import ComponentItem from '@/components/panels/right/component-item';
import { AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
import { useFlowContext } from '@/contexts/flow-context';
import { useTabsContext } from '@/contexts/tabs-context';
import { ComponentGroup } from '@/data/sidebar-components';
import { flowService } from '@/services/flow-service';
import { TabService } from '@/services/tab-service';
import { useState } from 'react';
import { toast } from 'sonner';

interface ComponentItemGroupProps {
  group: ComponentGroup;
  activeItem: string | null;
}

function waitForReactFlowMounted(timeoutMs = 4000): Promise<boolean> {
  const start = Date.now();
  return new Promise((resolve) => {
    const tick = () => {
      if (document.querySelector('.react-flow')) {
        setTimeout(() => resolve(true), 75);
        return;
      }
      if (Date.now() - start >= timeoutMs) {
        resolve(false);
        return;
      }
      requestAnimationFrame(tick);
    };
    tick();
  });
}

export function ComponentItemGroup({
  group,
  activeItem,
}: ComponentItemGroupProps) {
  const { name, icon: Icon, iconColor, items } = group;
  const { addComponentToFlow, enqueueComponentToAdd, flushPendingComponents } = useFlowContext();
  const { activeTabId, tabs, openTab, setActiveTab } = useTabsContext();
  const [mountingItem, setMountingItem] = useState<string | null>(null);
  const busy = mountingItem != null;

  const currentFlowName = (): string => {
    const tab = tabs.find((t) => t.id === activeTabId);
    if (tab?.type === 'flow' && tab.flow?.name) return tab.flow.name;
    const existing = tabs.find((t) => t.type === 'flow' && t.flow);
    return existing?.flow?.name || 'flow';
  };

  const ensureActiveFlowCanvas = async (): Promise<boolean> => {
    if (activeTabId?.startsWith('flow-') && document.querySelector('.react-flow')) {
      return true;
    }

    if (activeTabId?.startsWith('flow-')) {
      return waitForReactFlowMounted();
    }

    const existingFlowTab = tabs.find((t) => t.type === 'flow' && t.flow);
    if (existingFlowTab) {
      setActiveTab(existingFlowTab.id);
      return waitForReactFlowMounted();
    }

    try {
      const newFlow = await flowService.createFlow({
        name: 'Untitled Flow',
        description: 'Created when adding a component from the sidebar',
        nodes: [],
        edges: [],
        viewport: { x: 0, y: 0, zoom: 1 },
      });
      openTab(TabService.createFlowTab(newFlow));
      localStorage.setItem('lastSelectedFlowId', newFlow.id.toString());
      toast.success(`Opened "${newFlow.name}" to add components`);
      return waitForReactFlowMounted();
    } catch (error) {
      console.error('Failed to auto-create flow for component add:', error);
      toast.error('Could not open a flow canvas. Create a flow from the left sidebar first.');
      return false;
    }
  };

  const handleItemClick = async (componentName: string) => {
    if (busy) return;
    setMountingItem(componentName);
    try {
      const flowActiveWithCanvas =
        !!activeTabId?.startsWith('flow-') && !!document.querySelector('.react-flow');

      if (flowActiveWithCanvas) {
        await addComponentToFlow(componentName);
        toast.success(`Added ${componentName} to ${currentFlowName()}`);
        return;
      }

      const alreadyOnFlowTab = !!activeTabId?.startsWith('flow-');
      enqueueComponentToAdd(componentName);
      const ready = await ensureActiveFlowCanvas();
      if (!ready) {
        toast.error('Flow canvas did not become ready. Try opening a flow from the left sidebar.');
        return;
      }

      if (alreadyOnFlowTab) {
        await flushPendingComponents();
      }
      toast.success(`Added ${componentName} to ${currentFlowName()}`);
    } catch (error) {
      console.error('Failed to add component to flow:', error);
      toast.error(`Failed to add ${componentName}. Retry after the canvas finishes loading.`);
    } finally {
      setMountingItem(null);
    }
  };

  return (
    <AccordionItem key={name} value={name} className="border-none">
      <AccordionTrigger className="px-4 py-2 text-sm hover-bg hover:no-underline">
        <div className="flex items-center gap-2">
          <Icon size={16} className={iconColor} />
          <span className="capitalize">{name}</span>
        </div>
      </AccordionTrigger>
      <AccordionContent className="px-4">
        <div className="space-y-1">
          {items.map((item) => (
            <ComponentItem
              key={item.name}
              icon={item.icon}
              label={item.name}
              isActive={activeItem === item.name}
              disabled={busy && mountingItem !== item.name}
              mounting={mountingItem === item.name}
              onClick={() => handleItemClick(item.name)}
            />
          ))}
        </div>
      </AccordionContent>
    </AccordionItem>
  );
}
