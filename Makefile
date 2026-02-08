# Compiler settings
CC = gcc
CFLAGS = -Wall -Wextra -g -I.

# Tools
GENERATOR = sm-compiler.py
MAIN_SRC = main.c

# ---------------------------------------------------------
# PATTERN RULE
# ---------------------------------------------------------

%: %.yaml $(GENERATOR) $(MAIN_SRC)
	@echo "========================================"
	@echo " Building Target: $@ "
	@echo " Source Model:    $< "
	@echo "========================================"
	
	# 1. Generate C code using 'uv run python'
	uv run python $(GENERATOR) $<
	
	# 2. Compile the generated statemachine code
	$(CC) $(CFLAGS) -c statemachine.c -o statemachine.o
	
	# 3. Compile main.c 
	$(CC) $(CFLAGS) -c $(MAIN_SRC) -o main.o
	
	# 4. Link everything
	$(CC) $(CFLAGS) -o $@ main.o statemachine.o
	
	@echo "----------------------------------------"
	@echo "Success! Executable '$@' created."
	@echo "Run it with: ./$@"

# ---------------------------------------------------------
# UTILS
# ---------------------------------------------------------

view:
	dot -Tpng statemachine.dot -o statemachine.png
	@if [ -x "$$(command -v xdg-open)" ]; then xdg-open statemachine.png; \
	elif [ -x "$$(command -v open)" ]; then open statemachine.png; \
	else echo "Image created: statemachine.png"; fi

clean:
	rm -f *.o statemachine.c statemachine.h statemachine.dot statemachine.png
	rm -f manual.{aux,log,out,toc}
