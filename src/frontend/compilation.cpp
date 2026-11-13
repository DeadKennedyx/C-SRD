#include "csrd/frontend.hpp"
#include "csrd/config.hpp"
#include "clang/Tooling/ArgumentsAdjusters.h"
#include "clang/Tooling/CompilationDatabase.h"
#include "clang/Tooling/JSONCompilationDatabase.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/TargetSelect.h"
#include "llvm/Support/VirtualFileSystem.h"
#include <algorithm>
#include <filesystem>
#include <stdexcept>

namespace csrd {
namespace {
using namespace clang::tooling;
std::string absolute(const std::string &path, const std::string &directory) {
  auto file = std::filesystem::path(path);
  if (file.is_relative()) file = std::filesystem::path(directory) / file;
  return std::filesystem::absolute(file).lexically_normal().string();
}
// Deny opaque frontend state/extensions before loading it into this process.
// Ordinary driver options are interpreted by Clang, never approximated here.
void checkArguments(const std::vector<std::string> &arguments) {
  if (arguments.empty()) throw std::runtime_error("empty compilation command");
  for (const auto &arg : arguments) {
    for (const auto *prefix : {"-Xclang", "-Xpreprocessor", "-fplugin", "-load", "-plugin", "-add-plugin",
                              "-include-pch", "-include-pth", "-fmodules", "-fmodule-file", "-fmodule-map-file",
                              "-ivfsoverlay", "-vfsoverlay", "-cc1", "--config", "-working-directory"}) {
      if (arg == prefix || arg.rfind(std::string(prefix) + "=", 0) == 0)
        throw std::runtime_error("unsupported opaque compilation option: " + arg);
    }
    if (arg == "-specs" || arg.rfind("-specs=", 0) == 0 || arg == "--specs" || arg.rfind("--specs=", 0) == 0 || arg == "-wrapper")
      throw std::runtime_error("unsupported compiler-driver customization: " + arg);
    if (!arg.empty() && arg.front() == '@') throw std::runtime_error("unexpanded response file: " + arg);
  }
}
}
CompilationConfiguration loadCompilationConfiguration(const std::string &input,
    const FrontendOptions &options, bool preprocessing) {
  using namespace clang::tooling;
  CompilationConfiguration result;
  auto path = std::filesystem::path(options.compilationDatabase);
  if (std::filesystem::is_directory(path)) path /= "compile_commands.json";
  result.database = std::filesystem::absolute(path).lexically_normal().string();
  const auto buffer = llvm::MemoryBuffer::getFile(result.database);
  if (!buffer) throw std::runtime_error("cannot read compilation database: " + result.database);
  const auto text = (*buffer)->getBuffer();
  result.databaseHash = sha256(text.str());
  std::string error;
  auto db = JSONCompilationDatabase::loadFromBuffer(text, error, JSONCommandLineSyntax::AutoDetect);
  if (!db) throw std::runtime_error("invalid compilation database: " + error);
  const auto commands = db->getAllCompileCommands();
  const auto inputPath = std::filesystem::absolute(input).lexically_normal().string();
  auto directoryFor = [&](const CompileCommand &command) {
    return absolute(command.Directory, std::filesystem::path(result.database).parent_path().string());
  };
  std::vector<unsigned> selected;
  if (options.compileCommand) selected.push_back(*options.compileCommand);
  else for (unsigned i = 0; i < commands.size(); ++i)
    if (absolute(commands[i].Filename, directoryFor(commands[i])) == inputPath) selected.push_back(i);
  if (selected.size() != 1) throw std::runtime_error("require one matching compile command; use --compile-command INDEX to select a database entry explicitly");
  result.index = selected.front();
  if (result.index >= commands.size()) throw std::runtime_error("compile-command index out of range");
  const auto original = commands[result.index];
  result.directory = directoryFor(original);
  if (!std::filesystem::is_directory(result.directory)) throw std::runtime_error("compile-command working directory does not exist");
  result.source = absolute(original.Filename, result.directory);
  result.output = original.Output.empty() ? "" : absolute(original.Output, result.directory);
  result.originalArguments = original.CommandLine;
  // Clang's database wrapper handles GNU/Windows quoting and nested response files.
  // Relative directory fields are normalized in the single-command database below.
  class Single final : public CompilationDatabase {
    CompileCommand command;
  public:
    explicit Single(CompileCommand c) : command(std::move(c)) {}
    std::vector<CompileCommand> getCompileCommands(llvm::StringRef) const override { return {command}; }
    std::vector<CompileCommand> getAllCompileCommands() const override { return {command}; }
  };
  auto normalized = original; normalized.Directory = result.directory;
  auto expanded = expandResponseFiles(std::make_unique<Single>(normalized), llvm::vfs::getRealFileSystem());
  auto command = expanded->getAllCompileCommands().at(0);
  result.expandedArguments = command.CommandLine;
  checkArguments(result.expandedArguments);
  // Infer a cross target from compiler names such as aarch64-linux-gnu-gcc.
  // Clang's target-name inference consults LLVM's target registry.
  static const bool targetsInitialized = [] { llvm::InitializeAllTargets(); return true; }();
  (void)targetsInitialized;
  auto inferred = inferTargetAndDriverMode(std::make_unique<Single>(command));
  command = inferred->getAllCompileCommands().at(0);
  // Preserve original input spelling for preprocessing (__FILE__/__BASE_FILE__).
  // Frozen/replacement files explicitly reuse the selected build configuration.
  if (inputPath != result.source) command = transferCompileCommand(command, inputPath);
  command.CommandLine = getClangStripDependencyFileAdjuster()(command.CommandLine, inputPath);
  command.CommandLine = getClangStripOutputAdjuster()(command.CommandLine, inputPath);
  std::vector<std::string> flags;
  for (const auto &arg : command.CommandLine)
    if (arg != "-c" && arg != "-S" && arg != "-E" && arg != "-fsyntax-only" && arg != "-emit-llvm") flags.push_back(arg);
  auto position = std::find(flags.begin(), flags.end(), "--");
  const auto offset = unsigned(position - flags.begin());
  std::vector<std::string> extra = {preprocessing ? "-E" : "-fsyntax-only", "-resource-dir=" CSRD_RESOURCE_DIR,
                                  "-Wno-unused-command-line-argument", "-Wno-keyword-macro",
                                  "-Werror=unknown-pragmas", "-Werror=unknown-attributes"};
  if (std::filesystem::path(input).extension() == ".i") {
    extra.insert(extra.end(), {"-x", "cpp-output", "-Wno-gnu-line-marker"});
  }
  flags.insert(flags.begin() + offset, extra.begin(), extra.end());
  result.arguments = std::move(flags);
  return result;
}
}
