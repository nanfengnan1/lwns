export interface TerminalControls {
  connect(): Promise<void>;
  clear(): void;
}
