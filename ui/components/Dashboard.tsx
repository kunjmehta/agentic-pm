'use client';

interface Props {
  children?: React.ReactNode;
}

export default function Dashboard({ children }: Props) {
  return (
    <div className="dashboard-container">
      <div className="dashboard-content">
        {children || (
          <div className="dashboard-placeholder">
            <h2>Portfolio Dashboard</h2>
            <p>Live telemetry and portfolio data will appear here</p>
          </div>
        )}
      </div>
    </div>
  );
}
