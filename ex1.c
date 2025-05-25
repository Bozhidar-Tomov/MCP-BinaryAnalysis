#include <stdio.h>

void func(){
  long b = 0;
  long a = 0;
  char input[100];
  scanf("%s", &input);
  if(a == 0x5542474e49444f43 && b == 0x0000000053414752) {
    printf("SUCCESS!");
  } else {
    printf("Failure, try again.");
  }
}

int main(int argc, char* argv[]) {
  func();
  return 0;
}