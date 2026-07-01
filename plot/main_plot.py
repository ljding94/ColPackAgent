#!/opt/homebrew/bin/python3
from setup_plot import *
from demo_plot import plot_autonomous_demo, plot_interactive_demo, plot_autoresearch_demo
from eval_plot import plot_llm_eval

def main():
    #plot_autonomous_demo()
    #plot_interactive_demo()
    #plot_llm_eval()
    plot_autoresearch_demo()


if __name__ == "__main__":
    main()