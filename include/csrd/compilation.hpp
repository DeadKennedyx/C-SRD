#pragma once
#include <optional>
#include <string>
#include <vector>

namespace csrd {
// Compilation settings never belong to the representation planner.
struct FrontendOptions {
  std::string target, sysroot;
  std::vector<std::string> includeDirectories, definitions;
  std::string compilationDatabase;
  std::optional<unsigned> compileCommand;
};
struct CompilationConfiguration {
  std::string database, databaseHash, directory, source, output;
  unsigned index = 0;
  // Original compiler invocations are provenance, not shell commands to execute.
  std::vector<std::string> originalArguments, expandedArguments, arguments;
};
CompilationConfiguration loadCompilationConfiguration(const std::string &input,
    const FrontendOptions &options, bool preprocessing);
}
