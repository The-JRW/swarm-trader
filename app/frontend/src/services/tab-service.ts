import { Settings } from '@/components/settings/settings';
import { StrategiesPage } from '@/components/strategies/strategies-page';
import { FlowTabContent } from '@/components/tabs/flow-tab-content';
import { Flow } from '@/types/flow';
import { ReactNode, createElement } from 'react';

export interface TabData {
  type: 'flow' | 'settings' | 'strategies';
  title: string;
  flow?: Flow;
  metadata?: Record<string, any>;
}

export class TabService {
  static createTabContent(tabData: TabData): ReactNode {
    switch (tabData.type) {
      case 'flow':
        if (!tabData.flow) {
          throw new Error('Flow tab requires flow data');
        }
        return createElement(FlowTabContent, { flow: tabData.flow });
      
      case 'settings':
        return createElement(Settings);

      case 'strategies':
        return createElement(StrategiesPage);
      
      default:
        throw new Error(`Unsupported tab type: ${(tabData as TabData).type}`);
    }
  }

  static createFlowTab(flow: Flow): TabData & { content: ReactNode } {
    return {
      type: 'flow',
      title: flow.name,
      flow: flow,
      content: TabService.createTabContent({ type: 'flow', title: flow.name, flow }),
    };
  }

  static createSettingsTab(): TabData & { content: ReactNode } {
    return {
      type: 'settings',
      title: 'Settings',
      content: TabService.createTabContent({ type: 'settings', title: 'Settings' }),
    };
  }

  static createStrategiesTab(): TabData & { content: ReactNode } {
    return {
      type: 'strategies',
      title: 'Strategies',
      content: TabService.createTabContent({ type: 'strategies', title: 'Strategies' }),
    };
  }

  // Restore tab content for persisted tabs (used when loading from localStorage)
  static restoreTabContent(tabData: TabData): ReactNode {
    return TabService.createTabContent(tabData);
  }

  // Helper method to restore a complete tab from saved data
  static restoreTab(savedTab: TabData): TabData & { content: ReactNode } {
    switch (savedTab.type) {
      case 'flow':
        if (!savedTab.flow) {
          throw new Error('Flow tab requires flow data for restoration');
        }
        return TabService.createFlowTab(savedTab.flow);
      
      case 'settings':
        return TabService.createSettingsTab();

      case 'strategies':
        return TabService.createStrategiesTab();
      
      default:
        throw new Error(`Cannot restore unsupported tab type: ${(savedTab as TabData).type}`);
    }
  }
}
