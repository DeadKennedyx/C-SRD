#include "csrd/control_regions.hpp"
#include <algorithm>
#include <numeric>
#include <stdexcept>

namespace csrd {
std::set<int> controlExits(const ControlFrame &frame) {
  std::set<int> exits, visited;
  std::vector<int> work{frame.entry};
  while (!work.empty()) {
    const auto id=work.back();work.pop_back();
    if (id < 0) { if (id < ControlContinue) throw std::invalid_argument("invalid control terminal"); exits.insert(id); continue; }
    if (!visited.insert(id).second) continue;
    const auto &node=frame.nodes.at(unsigned(id));
    if (node.kind==ControlKind::Return) continue;
    work.push_back(node.yes);
    if (node.kind==ControlKind::Branch) work.push_back(node.no);
  }
  return exits;
}
void emitControlFrame(ControlFrame &frame, uint64_t seed, const std::string &function,
                      const std::set<std::string> &reserved) {
  uint64_t hash = UINT64_C(14695981039346656037);
  for (unsigned char c : function + ":" + std::to_string(frame.begin)) { hash ^= c; hash *= UINT64_C(1099511628211); }
  uint64_t cursor = hash ^ seed;
  auto random = [&]() {
    uint64_t value = (cursor += UINT64_C(0x9e3779b97f4a7c15));
    value = (value ^ (value >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
    value = (value ^ (value >> 27)) * UINT64_C(0x94d049bb133111eb);
    return value ^ (value >> 31);
  };
  std::set<uint32_t> states;
  for (auto &node : frame.nodes) do { node.state = 3u + uint32_t(random() & UINT64_C(0x3fffffff)); } while (!states.insert(node.state).second);
  std::vector<unsigned> order(frame.nodes.size());
  std::iota(order.begin(), order.end(), 0);
  for (unsigned i = unsigned(order.size()); i > 1; --i) std::swap(order[i-1], order[random() % i]);
  unsigned serial = 0;
  do { frame.stateName = "csrd_control_" + std::to_string(frame.begin) + "_" + std::to_string(serial++); } while (reserved.count(frame.stateName));
  auto state = [&](int edge) { return std::to_string(edge < 0 ? unsigned(-edge-1) : frame.nodes.at(unsigned(edge)).state) + "UL"; };
  auto assignment = [&](int edge) { return frame.stateName + " = " + state(edge) + ";"; };
  auto &out = frame.emitted;
  const auto exits = controlExits(frame);
  frame.outerBreak = exits.count(ControlBreak); frame.outerContinue = exits.count(ControlContinue);
  out = "{ unsigned long "; frame.stateDeclarationOffset = unsigned(out.size());
  out += frame.stateName + " = " + state(frame.entry) + "; while (1) { ";
  if (!exits.empty()) out += "if (" + frame.stateName + " <= 2UL) { break; } ";
  out += "switch (" + frame.stateName + ") { ";
  // A constant loop condition preserves divergence for source for(;;)/while(1).
  // A data-dependent loop condition could enable C11's termination assumption.
  for (const auto index : order) {
    auto &node = frame.nodes[index];
    out += "case " + state(int(index)) + ": { ";
    if (node.kind == ControlKind::Effect || node.kind == ControlKind::Return) {
      node.emittedOffset = unsigned(out.size()); out += node.text + "; ";
    } else if (node.kind == ControlKind::Branch) {
      out += "if ("; node.emittedOffset = unsigned(out.size()); out += node.text + ") { " + assignment(node.yes) + " } else { " + assignment(node.no) + " } ";
    }
    if (node.kind == ControlKind::Effect || node.kind == ControlKind::Jump) out += assignment(node.yes) + " ";
    if (node.kind != ControlKind::Return) out += "break; ";
    out += "} ";
  }
  out += "default: { " + assignment(ControlEnd) + " break; } } } ";
  if (frame.outerBreak) out += exits.size() == 1 ? "break; " : "if (" + frame.stateName + " == 1UL) { break; } ";
  if (frame.outerContinue) out += exits.count(ControlEnd) ? "if (" + frame.stateName + " == 2UL) { continue; } " : "continue; ";
  const auto originalLines = std::count(frame.originalText.begin(), frame.originalText.end(), '\n');
  const auto emittedLines = std::count(out.begin(), out.end(), '\n');
  if (emittedLines > originalLines) throw std::logic_error("control emission changed line budget");
  out += std::string(size_t(originalLines-emittedLines), '\n') + "}";
}

void prepareControlFrames(std::vector<ControlFrame *> frames) {
  std::sort(frames.begin(), frames.end(), [](const auto *a, const auto *b) { return a->begin < b->begin; });
  int64_t delta = 0;
  unsigned previousEnd = 0;
  for (auto *frame : frames) {
    if (frame->begin < previousEnd) throw std::logic_error("control regions overlap");
    frame->candidateBegin = unsigned(int64_t(frame->begin) + delta);
    frame->candidateEnd = frame->candidateBegin + unsigned(frame->emitted.size());
    int64_t parent = frame->parentBegin;
    for (const auto *other : frames) if (other->end <= frame->parentBegin)
      parent += int64_t(other->emitted.size()) - int64_t(other->end-other->begin);
    frame->candidateParentBegin = unsigned(parent);
    delta += int64_t(frame->emitted.size()) - int64_t(frame->end-frame->begin);
    previousEnd = frame->end;
  }
}
} // namespace csrd
