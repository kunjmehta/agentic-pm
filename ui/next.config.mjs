/** @type {import('next').NextConfig} */
const nextConfig = {
  // Keep Daytona SDK (and its Node.js-only deps) out of the browser bundle
  serverExternalPackages: [
    '@daytonaio/sdk',
    '@daytona/api-client',
    '@daytona/toolbox-api-client',
    '@aws-sdk/client-s3',
    '@aws-sdk/lib-storage',
    '@opentelemetry/sdk-node',
  ],
  webpack: (config, { isServer }) => {
    // Increase memory limit and disable persistent caching
    config.cache = false;

    // Increase Node memory limit if needed
    if (!isServer) {
      config.optimization = {
        ...config.optimization,
        moduleIds: 'deterministic',
        runtimeChunk: 'single',
        splitChunks: {
          chunks: 'all',
          cacheGroups: {
            vendor: {
              test: /[\\/]node_modules[\\/]/,
              name: 'vendors',
              priority: 10,
            },
          },
        },
      };
    }

    return config;
  },
};

export default nextConfig;
